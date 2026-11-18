# Copyright 2026 AlphaAvatar project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Stored credentials: private, exact, never over the environment, and committed with the
default bundle by one settings replacement. A credential empty or blank where it is set is no
credential: the next source's value takes its place, and every reader names it missing."""

from __future__ import annotations

import asyncio
import os
import signal
import stat
import subprocess
import sys
import threading
from pathlib import Path
from unittest import mock

import pytest

from alphaavatar.agents.utils import credential, resolve_env_placeholders
from alphaavatar.agents.utils.env_utils import server_key
from alphaavatar.host.configs.bundles import ConfigReferenceError, read_settings
from alphaavatar.host.configs.credentials import (
    credentials_path,
    load_credentials,
    load_environment,
    stored_credentials,
)
from alphaavatar.host.configs.template import create_bundle
from alphaavatar.host.service.sessions.livekit.config import LiveKitCredentials
from alphaavatar.host.workspace import ApplicationPaths

# Quotes, backslashes, dollar interpolation and spaces survive as written.
AWKWARD = "sk-\"quoted\"\\path ${HOME} $OTHER 'single' end"


def stored(paths: ApplicationPaths) -> list[str]:
    return sorted(path.name for path in paths.settings_dir.glob("credentials-*.env"))


def test_credentials_are_private_exact_and_never_override_the_environment(tmp_path: Path) -> None:
    paths = ApplicationPaths.from_root(tmp_path / "home")
    first = {"OPENAI_API_KEY": AWKWARD, "LIVEKIT_URL": "wss://a.invalid"}
    create_bundle(paths, "alpha", avatar_id="alpha", make_default=True, credentials=first)
    path = credentials_path(paths)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert read_settings(paths) == {"default_bundle": "alpha", "credentials": path.name}
    with mock.patch.dict(os.environ, {"LIVEKIT_URL": "wss://set.invalid"}):
        os.environ.pop("OPENAI_API_KEY", None)
        settings = load_credentials(paths)
        assert settings.values == {"default_bundle": "alpha", "credentials": path.name}
        assert "wss://a.invalid" not in repr(settings)  # A read never shows the values.
        assert os.environ["OPENAI_API_KEY"] == AWKWARD
        assert os.environ["LIVEKIT_URL"] == "wss://set.invalid"  # Set already: kept.

    # A later bundle keeps the other names, in a new file; the one it replaced is gone.
    second = {"QDRANT_URL": "http://q.invalid", "LIVEKIT_URL": "wss://b"}
    create_bundle(paths, "beta", avatar_id="beta", make_default=True, credentials=second)
    assert stored_credentials(paths) == first | second
    assert stored(paths) == [credentials_path(paths).name] != [path.name]
    # Without credentials to store, the stored ones stay as named.
    create_bundle(paths, "gamma", avatar_id="gamma", make_default=True)
    assert stored_credentials(paths) == first | second


SERVER = server_key("https://gpu.invalid:8000/v1")  # A server of one's own's key variable.
# Each variable as the environment, the .env file and the stored credentials hold it (None:
# not there), and what loading leaves: the first neither empty nor blank, as it is set.
LAYERS = {
    "OPENAI_API_KEY": ("environment", "file", "stored", "environment"),
    "LIVEKIT_URL": ("", "file", "stored", "file"),
    "LIVEKIT_API_KEY": (" \t", "", "stored", "stored"),
    "MY_TTS_KEY": (None, " ", "stored", "stored"),  # A bundle's own api_key_env.
    SERVER: ("", None, "stored", "stored"),
    "TAVILY_API_KEY": (None, " spaced  ", "stored", " spaced  "),
    "QDRANT_API_KEY": (None, None, "  ", None),  # Stored blank by hand: none.
    "LIVEKIT_API_SECRET": ("", " ", None, None),  # None anywhere: missing.
}


def test_each_variable_takes_the_first_value_neither_empty_nor_blank(tmp_path: Path) -> None:
    # The file ENV_FILE names also chooses the home, whose stored credentials come last.
    paths = ApplicationPaths.from_root(tmp_path / "home")
    kept = {name: layer[2] for name, layer in LAYERS.items() if layer[2] and layer[2].strip()}
    create_bundle(paths, "alpha", avatar_id="alpha", make_default=True, credentials=kept)
    with credentials_path(paths).open("a") as stored:  # One no setup would store.
        stored.write('QDRANT_API_KEY="  "\n')
    lines = [f'{name}="{layer[1]}"' for name, layer in LAYERS.items() if layer[1] is not None]
    (tmp_path / "chosen.env").write_text("\n".join([f"ALPHAAVATAR_HOME={paths.root}", *lines]))
    environment = {name: layer[0] for name, layer in LAYERS.items() if layer[0] is not None}
    with mock.patch.dict(os.environ, {"ENV_FILE": str(tmp_path / "chosen.env")} | environment):
        for name in (*LAYERS, "ALPHAAVATAR_HOME"):
            if name not in environment:
                os.environ.pop(name, None)
        settings = load_environment()
        assert settings.values["default_bundle"] == "alpha"
        assert {name: credential(name) for name in LAYERS} == {
            name: layer[3] for name, layer in LAYERS.items()
        }
        # What none holds is not set from a blank line: only an empty one already there stays.
        assert "QDRANT_API_KEY" not in os.environ and os.environ["LIVEKIT_API_SECRET"] == ""
        with pytest.raises(ValueError, match=r"^LIVEKIT_API_SECRET is required$"):
            LiveKitCredentials.from_env()


def _readers(name: str):
    """Each reader of a credential, with ``name`` for its variable where it takes one."""
    from alphaavatar.agents.avatar.provider.factory import create_embedding_model, create_llm_model
    from alphaavatar.agents.configs.plugins.foundation.provider_config import ProviderTaskConfig
    from alphaavatar.plugins.deepresearch.tavily import TavilyDeepResearchTool
    from alphaavatar.plugins.provider.openai.llms.client import ResponsesClient
    from alphaavatar.plugins.provider.openai.llms.config import OpenAIClientConfig
    from alphaavatar.plugins.voice.stt.openai_realtime import OpenAIRealtimeSTT
    from alphaavatar.plugins.voice.stt.openai_segment import OpenAISegmentSTT
    from alphaavatar.plugins.voice.tts.openai import OpenAITTS
    from alphaavatar.plugins.voice.tts.voiceai import VoiceAITTS

    async def first_use(client) -> None:  # Each client takes its key when first used.
        try:
            await (client.get() if isinstance(client, ResponsesClient) else client._model())
        finally:
            await client.aclose()

    task = {"model": "tasks", "extra": {"api_key_env": name}}
    own = {"api_key_env": SERVER, "base_url": "https://gpu.invalid:8000/v1"}
    return {
        name: [
            lambda: asyncio.run(first_use(create_llm_model(ProviderTaskConfig(**task)))),
            lambda: asyncio.run(
                first_use(ResponsesClient(OpenAIClientConfig(api_key_env=name), timeout=1))
            ),
            lambda: OpenAITTS(model="speak", speaker="voice", api_key_env=name),
            lambda: VoiceAITTS(model="speak", api_key_env=name),
            lambda: OpenAISegmentSTT(model="transcribe", api_key_env=name).stream(source_id="s"),
            lambda: OpenAIRealtimeSTT(api_key_env=name).stream(source_id="s"),
            lambda: resolve_env_placeholders({"Authorization": f"Bearer <{name}>"}),
        ],
        SERVER: [
            lambda: create_embedding_model(
                ProviderTaskConfig.model_validate({"kind": "embedding", "model": "e", "extra": own})
            )
        ],
        "TAVILY_API_KEY": [lambda: TavilyDeepResearchTool(session_path=None)],
    }


@pytest.mark.parametrize("blank", ["", "  \t"], ids=["empty", "blank"])
def test_a_credential_empty_or_blank_is_missing_to_every_reader_by_its_name(blank: str) -> None:
    # A bundle's own api_key_env, a server of one's own's and a plugin's fixed one: each
    # reader refuses to start without it and names the variable, never sending a blank key.
    readers = _readers("MY_KEY")
    with mock.patch.dict(os.environ, dict.fromkeys(readers, blank)):
        for name, made in readers.items():
            for make in made:
                with pytest.raises(Exception, match=name):
                    make()


@pytest.mark.parametrize(
    "values",
    [
        {"lower_case": "x"},
        {"OPENAI_API_KEY": ""},
        {"OPENAI_API_KEY": " \t"},
        {"OPENAI_API_KEY": "a\nB=c"},
    ],
)
def test_unsafe_credentials_are_refused_before_anything_changes(
    tmp_path: Path, values: dict[str, str]
) -> None:
    paths = ApplicationPaths.from_root(tmp_path / "home")
    kept = {"LIVEKIT_URL": "wss://a.invalid"}
    create_bundle(paths, "alpha", avatar_id="alpha", make_default=True, credentials=kept)
    settings, files = read_settings(paths), stored(paths)
    with pytest.raises(ValueError):
        create_bundle(paths, "beta", avatar_id="beta", make_default=True, credentials=values)
    assert (read_settings(paths), stored(paths)) == (settings, files)
    assert stored_credentials(paths) == kept
    assert not (paths.configs.bundles_dir / "beta.yaml").exists()


KILLED = """
import os, signal, sys
from alphaavatar.host.configs.template import create_bundle
from alphaavatar.host.service.sessions.livekit.config import LiveKitCredentials
from alphaavatar.host.workspace import ApplicationPaths

replace = os.replace

def killed(source, target):
    if os.path.basename(target) == "settings.yaml":
        os.kill(os.getpid(), signal.SIGKILL)  # Nothing runs after this, not even cleanup.
    return replace(source, target)

os.replace = killed
paths = ApplicationPaths.from_root(sys.argv[1])
create_bundle(paths, "beta", avatar_id="beta", make_default=True, credentials={"OPENAI_API_KEY": "new"})
"""


def test_a_kill_before_the_settings_replacement_leaves_every_bundle_reading_what_it_read(
    tmp_path: Path,
) -> None:
    paths = ApplicationPaths.from_root(tmp_path / "home")
    old = {"OPENAI_API_KEY": "old", "LIVEKIT_URL": "wss://a.invalid"}
    create_bundle(paths, "alpha", avatar_id="alpha", make_default=True, credentials=old)
    settings = read_settings(paths)
    killed = subprocess.run([sys.executable, "-c", KILLED, str(paths.root)], timeout=60)
    assert killed.returncode == -signal.SIGKILL
    # The new credentials were written, and nothing names them: the old default reads the old.
    assert len(stored(paths)) == 2
    assert read_settings(paths) == settings and stored_credentials(paths) == old
    # The next store, under the same lock, removes what the killed run wrote.
    create_bundle(paths, "gamma", avatar_id="gamma", make_default=True, credentials={"X": "1"})
    assert stored(paths) == [credentials_path(paths).name]
    assert stored_credentials(paths) == old | {"X": "1"}


@pytest.mark.parametrize(
    "settings",
    [b"default_bundle: [\n", b"credentials: ../outside.env\n", b"default_bundle: \xff\n", None],
    ids=["invalid YAML", "a path", "not UTF-8", "unreadable"],
)
def test_settings_that_name_no_stored_file_load_none_and_setup_refuses_them(
    tmp_path: Path, settings: bytes | None
) -> None:
    paths = ApplicationPaths.from_root(tmp_path / "home")
    create_bundle(paths, "alpha", avatar_id="alpha", make_default=True, credentials={"A": "1"})
    (paths.root / "outside.env").write_text('A="outside"\n')
    paths.settings_file.unlink()
    if settings is None:
        paths.settings_file.mkdir()  # Cannot be read as a file, whoever runs the test.
    else:
        paths.settings_file.write_bytes(settings)
    # Loading reads no stored value, from settings' directory or beyond; storing refuses.
    with mock.patch.dict(os.environ, clear=True):
        loaded = load_credentials(paths)
        assert isinstance(loaded.error, ConfigReferenceError) and "A" not in os.environ
    assert loaded.credentials == {}
    with pytest.raises(ConfigReferenceError):
        stored_credentials(paths)
    with pytest.raises(ConfigReferenceError):
        loaded.checked()  # Choosing the default refuses them.


def without_waiting(read, pipe: Path):
    """read(), failing if it waits on the pipe: opening the pipe's other end lets it finish."""
    done: list = []
    thread = threading.Thread(target=lambda: done.append(read()), daemon=True)
    thread.start()
    thread.join(10)
    waited = thread.is_alive()
    if waited:
        os.close(os.open(pipe, os.O_RDWR | os.O_NONBLOCK))  # Both ends, so either wait ends.
        thread.join(10)
    assert not waited, f"waited on the pipe in place of {pipe.name}"
    return done[0]


@pytest.mark.parametrize("replaced", ["settings", "stored file"])
def test_a_pipe_in_place_of_a_settings_file_is_refused_without_waiting(
    tmp_path: Path, replaced: str
) -> None:
    paths = ApplicationPaths.from_root(tmp_path / "home")
    create_bundle(paths, "alpha", avatar_id="alpha", make_default=True, credentials={"A": "1"})
    pipe = paths.settings_file if replaced == "settings" else credentials_path(paths)
    pipe.unlink()
    os.mkfifo(pipe)
    with mock.patch.dict(os.environ, clear=True):
        loaded = without_waiting(lambda: load_credentials(paths), pipe)
        assert "A" not in os.environ
    reason = "Settings cannot be read" if replaced == "settings" else "Stored credentials cannot"
    assert isinstance(loaded.error, ConfigReferenceError) and reason in str(loaded.error)
    assert stat.S_ISFIFO(pipe.lstat().st_mode)  # Left as it is.


def test_settings_naming_a_stored_file_that_is_gone_say_it_is_missing(tmp_path: Path) -> None:
    paths = ApplicationPaths.from_root(tmp_path / "home")
    create_bundle(paths, "alpha", avatar_id="alpha", make_default=True, credentials={"A": "1"})
    gone = credentials_path(paths)
    gone.unlink()
    # Named again when the settings are read again: missing, not settings that keep changing.
    with mock.patch.dict(os.environ, clear=True):
        error = load_credentials(paths).error
    assert str(error) == f"Stored credentials are missing: {gone}"


def test_a_setup_committing_meanwhile_changes_neither_the_default_nor_the_credentials_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alphaavatar.host.configs import bundles
    from alphaavatar.host.configs.bundles import select_configuration

    paths = ApplicationPaths.from_root(tmp_path / "home")
    first = {"A": "first"}
    create_bundle(paths, "alpha", avatar_id="alpha", make_default=True, credentials=first)
    original, committed = bundles.read_settings, []

    def committing(paths_: ApplicationPaths):
        settings = original(paths_)
        if not committed:
            committed.append(True)
            create_bundle(
                paths, "gamma", avatar_id="gamma", make_default=True, credentials={"A": "3"}
            )
        return settings

    with mock.patch.dict(os.environ, {"ALPHAAVATAR_HOME": str(paths.root)}):
        # A start reads the settings and their credentials; a setup then commits another
        # default and removes the file the start read: the start keeps both from its one read.
        os.environ.pop("A", None)
        read = load_credentials(paths)
        create_bundle(paths, "beta", avatar_id="beta", make_default=True, credentials={"A": "2"})
        assert select_configuration(None, settings=read).bundle == "alpha"
        assert os.environ["A"] == "first"
        assert read_settings(paths)["default_bundle"] == "beta"

        # A setup committing between reading the settings and opening the file they name: the
        # file is gone, so the settings are read again, and both come from the new read.
        monkeypatch.setattr(bundles, "read_settings", committing)
        os.environ.pop("A")
        again = load_credentials(paths)
        assert committed and again.values["default_bundle"] == "gamma"
        assert again.credentials == {"A": "3"} and os.environ["A"] == "3"


COMMITTING = """
import sys
from alphaavatar.host.cli.app import main
from alphaavatar.host.configs import application_paths, credentials
from alphaavatar.host.configs.template import create_bundle
from alphaavatar.host.service.sessions.livekit.config import LiveKitCredentials

load = credentials.load_environment


def committing(overrides=()):
    read = load(overrides)  # Then a setup commits another default, with its credentials.
    create_bundle(
        application_paths(), "beta", avatar_id="beta", make_default=True,
        sections={"router": "plugin: absent\\n"}, credentials={"A": "2"},
    )
    return read


credentials.load_environment = committing
sys.exit(main(sys.argv[1:]))
"""


@pytest.mark.parametrize("command", [["config", "check"], ["start"], ["doctor"]])
def test_each_command_takes_the_default_from_the_read_its_credentials_came_from(
    command: list[str], home: Path
) -> None:
    from alphaavatar.host.configs import application_paths

    paths = application_paths()
    old = {"persona": "plugin: absent\n"}  # Each default fails where it is told apart.
    create_bundle(paths, "alpha", avatar_id="alpha", make_default=True, sections=old)
    ran = subprocess.run(
        [sys.executable, "-c", COMMITTING, *command],
        capture_output=True,
        text=True,
        timeout=120,
        env=os.environ | {"ALPHAAVATAR_HOME": str(home)},
    )
    assert read_settings(paths)["default_bundle"] == "beta"  # Committed meanwhile.
    assert "persona.plugin" in ran.stdout + ran.stderr, ran.stderr
    assert "router.plugin" not in ran.stdout + ran.stderr
