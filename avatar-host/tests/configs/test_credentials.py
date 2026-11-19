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


# The .env file's lines, the environment's value of each name (None: unset) and the one loading
# leaves. The file loads as python-dotenv loads it: what the environment sets stays, empty too,
# and ${NAME} reads it there first; then a credential empty or blank takes the file's value.
ORDINARY = {
    "CUDA_VISIBLE_DEVICES": ("0", "", ""),  # Empty: no GPU, whatever the file says.
    "HTTPS_PROXY": ("http://proxy.invalid:3128", "", ""),
    "ALPHAAVATAR_MODEL_OFFLINE": ("1", "", ""),  # Empty: downloads on.
    "API_HOST": ("dev.example", "prod.example", "prod.example"),
    "OPENAI_BASE_URL": ("https://${API_HOST}/v1", None, "https://prod.example/v1"),
    "NO_PROXY": ("", None, ""),  # Its empty line sets it empty.
    "OPENAI_API_KEY": ("from-file", " \t", "from-file"),
    "MODEL_HEADER": ("Bearer ${OPENAI_API_KEY}", None, "Bearer  \t"),  # The environment's.
    "ALPHAAVATAR_HOME": ("/srv/from-file", "", "/srv/from-file"),  # Empty: unset, as it was.
    "LIVEKIT_API_SECRET": ("", None, ""),  # Empty, a credential none holds.
}


def test_the_file_loads_as_python_dotenv_loads_it_and_only_credentials_take_its_values(
    tmp_path: Path,
) -> None:
    from alphaavatar.agents.utils import gpu_available
    from alphaavatar.agents.utils.files.model.model_files import models_offline

    lines = [f'{name}="{line}"' for name, (line, _, _) in ORDINARY.items()]
    (tmp_path / "chosen.env").write_text("\n".join(lines))
    environment = {name: set_ for name, (_, set_, _) in ORDINARY.items() if set_ is not None}
    with mock.patch.dict(os.environ, {"ENV_FILE": str(tmp_path / "chosen.env")} | environment):
        for name in [*(ORDINARY.keys() - environment.keys()), "HF_HUB_OFFLINE"]:
            os.environ.pop(name, None)  # The sandbox's offline switch, the other one read.
        load_environment()
        assert {name: os.environ.get(name) for name in ORDINARY} == {
            name: left for name, (_, _, left) in ORDINARY.items()
        }
        assert gpu_available() is False and models_offline() is False


def test_the_file_is_parsed_once_against_the_environment_it_loads_into(tmp_path: Path) -> None:
    """A reference's default, and a variable the file sets after it: read again once loaded,
    the reference would read what the first read set, and the credential would take that.
    PYTHON_DOTENV_DISABLED disables loading, as python-dotenv's own does."""
    (tmp_path / "chosen.env").write_text(
        "OPENAI_API_KEY=${SHARED_KEY:-file-default}\nSHARED_KEY=file-secondary\n"
    )
    variables = {"ENV_FILE": str(tmp_path / "chosen.env"), "OPENAI_API_KEY": ""}
    with mock.patch.dict(os.environ, variables):
        os.environ.pop("SHARED_KEY", None)
        settings = load_environment()
        assert settings.file == {"OPENAI_API_KEY": "file-default", "SHARED_KEY": "file-secondary"}
        assert credential("OPENAI_API_KEY") == "file-default"
        assert os.environ["SHARED_KEY"] == "file-secondary"
    with mock.patch.dict(os.environ, variables | {"PYTHON_DOTENV_DISABLED": "1"}):
        os.environ.pop("SHARED_KEY", None)
        assert load_environment().file == {} and "SHARED_KEY" not in os.environ
        assert os.environ["OPENAI_API_KEY"] == ""


# A variable a bundle names for its key, MODEL_AUTH, as the environment, the .env file and the
# stored credentials hold it, and what loading the bundle leaves: no name says it is one.
NAMED = [
    ("", "from-file", None, "from-file"),
    (" \t", "from-file", "stored-old", "from-file"),  # Neither passes over the file's.
    ("", " ", "stored", "stored"),
    ("set", "from-file", "stored-old", "set"),
    ("", None, None, None),
]


@pytest.mark.parametrize(
    ("environment", "file", "stored", "left"),
    NAMED,
    ids=["file", "file-before-stored", "stored", "environment", "missing"],
)
def test_a_variable_a_bundle_names_takes_the_first_value_neither_empty_nor_blank(
    tmp_path: Path, environment: str, file: str | None, stored: str | None, left: str | None
) -> None:
    from alphaavatar.host.configs import load_application, select_configuration

    paths = ApplicationPaths.from_root(tmp_path / "home")
    kept = {"MODEL_AUTH": stored} if stored else None
    create_bundle(paths, "alpha", avatar_id="alpha", make_default=True, credentials=kept)
    lines = [f"ALPHAAVATAR_HOME={paths.root}", "MCP_PAT=pat-from-file", "GITHUB_PAT=gh-file"]
    lines += [] if file is None else [f'MODEL_AUTH="{file}"']
    (tmp_path / "chosen.env").write_text("\n".join(lines))
    overrides = [  # Its speech's key, and two MCP servers': names of its own choosing.
        "voice.tts.api_key_env=MODEL_AUTH",
        "tools.mcp.plugin=default",
        "tools.mcp.enabled=true",
        "tools.mcp.servers.docs.url=https://mcp.invalid/",
        "tools.mcp.servers.docs.headers.Authorization=Bearer <MCP_PAT>",
        "tools.mcp.servers.code.url=https://code.invalid/",
        "tools.mcp.servers.code.headers.Authorization=Bearer ${oc.env:GITHUB_PAT}",
    ]
    variables = {"ENV_FILE": str(tmp_path / "chosen.env"), "MODEL_AUTH": environment}
    with mock.patch.dict(os.environ, variables | {"MCP_PAT": "", "GITHUB_PAT": ""}):
        os.environ.pop("ALPHAAVATAR_HOME", None)
        settings = load_environment()
        config = load_application(
            select_configuration(None, overrides, settings), overrides, settings
        )
        assert credential("MODEL_AUTH") == left
        servers = config.avatar.tools.mcp.servers
        assert {key: server["headers"] for key, server in servers.items()} == {
            "docs": {"Authorization": "Bearer pat-from-file"},
            "code": {"Authorization": "Bearer gh-file"},  # Filled before it is interpolated.
        }
        # Without the read loading made, a configuration fills nothing.
        os.environ["MODEL_AUTH"] = ""
        load_application(select_configuration(None, overrides, settings), overrides)
        assert os.environ["MODEL_AUTH"] == ""


def _hidden() -> set[str]:
    from alphaavatar.core.log.records import HIDDEN_ENV

    return set(os.environ.get(HIDDEN_ENV, "").split(","))


def test_in_an_mcp_server_only_authorization_interpolates_a_credential(tmp_path: Path) -> None:
    """``${oc.env:NAME}`` in an Authorization header, however cased, is a credential: empty or
    blank, it takes the .env file's value, and logs hide it. In another header it reads an
    ordinary variable as the environment holds it, empty too, and logs show it."""
    from alphaavatar.core.log.records import Redactor
    from alphaavatar.host.configs import load_application, select_configuration

    paths = ApplicationPaths.from_root(tmp_path / "home")
    create_bundle(paths, "alpha", avatar_id="alpha", make_default=True)
    (paths.configs.profiles_dir / "alpha/plugins/tools/tools.yaml").write_text(
        "mcp:\n  plugin: default\n  enabled: true\n  servers:\n"
        "    docs:\n      url: https://mcp.invalid/\n"
        "      headers:\n        Authorization: Bearer ${oc.env:GITHUB_PAT}\n"
        "        X-Region: ${oc.env:REGION}\n"
        "    code:\n      url: https://code.invalid/\n"
        "      headers:\n        authorization: token ${oc.env:CODE_PAT}\n"
    )
    lines = [f"ALPHAAVATAR_HOME={paths.root}", "GITHUB_PAT=gh-file", "CODE_PAT=code-file"]
    (tmp_path / "chosen.env").write_text("\n".join([*lines, "REGION=us-east-1"]))
    variables = {"GITHUB_PAT": "", "CODE_PAT": " ", "REGION": ""}
    with mock.patch.dict(os.environ, {"ENV_FILE": str(tmp_path / "chosen.env")} | variables):
        os.environ.pop("ALPHAAVATAR_HOME", None)
        settings = load_environment()
        config = load_application(select_configuration(None, (), settings), (), settings)
        servers = config.avatar.tools.mcp.servers
        assert {key: server["headers"] for key, server in servers.items()} == {
            "docs": {"Authorization": "Bearer gh-file", "X-Region": ""},
            "code": {"authorization": "token code-file"},
        }
        assert os.environ["REGION"] == "" and "REGION" not in _hidden()
        os.environ["REGION"] = "us-east-1"
        shown = Redactor()("refused gh-file and code-file at https://mcp.invalid/ in us-east-1")
        assert shown == "refused [redacted] and [redacted] at https://mcp.invalid/ in us-east-1"


# A variable an api_key_env names by interpolation, by TTS_KEY_NAME or else its default, as the
# environment, the .env file and the stored credentials hold it, and what loading leaves.
CHOSEN = [
    (None, "MODEL_AUTH", "", "from-file", None, "from-file"),
    (None, "MODEL_AUTH", " ", "from-file", "stored-old", "from-file"),
    ("CHOSEN_AUTH", "CHOSEN_AUTH", "", "from-file", None, "from-file"),
    ("CHOSEN_AUTH", "CHOSEN_AUTH", "auth-set", "from-file", "stored-old", "auth-set"),
]


@pytest.mark.parametrize(
    ("chooses", "chosen", "environment", "file", "stored", "left"),
    CHOSEN,
    ids=["default", "default-file-before-stored", "chosen", "chosen-environment"],
)
def test_the_variable_an_interpolated_api_key_env_names_is_a_credential(
    tmp_path: Path,
    chooses: str | None,
    chosen: str,
    environment: str,
    file: str,
    stored: str | None,
    left: str,
) -> None:
    from alphaavatar.core.log.records import Redactor
    from alphaavatar.host.configs import load_application, select_configuration

    paths = ApplicationPaths.from_root(tmp_path / "home")
    kept = {chosen: stored} if stored else None
    create_bundle(paths, "alpha", avatar_id="alpha", make_default=True, credentials=kept)
    lines = [f"ALPHAAVATAR_HOME={paths.root}", f'{chosen}="{file}"']
    (tmp_path / "chosen.env").write_text("\n".join(lines))
    overrides = ["voice.tts.api_key_env=${oc.env:TTS_KEY_NAME,MODEL_AUTH}"]
    variables = {"ENV_FILE": str(tmp_path / "chosen.env"), chosen: environment}
    with mock.patch.dict(os.environ, variables):
        for name in ("ALPHAAVATAR_HOME", *([] if chooses else ["TTS_KEY_NAME"])):
            os.environ.pop(name, None)
        if chooses:
            os.environ["TTS_KEY_NAME"] = chooses
        settings = load_environment()
        config = load_application(
            select_configuration(None, overrides, settings), overrides, settings
        )
        assert config.avatar.voice.tts.api_key_env == chosen
        assert credential(chosen) == left
        # The name it holds is no secret; the value of the one it names is.
        assert chosen in _hidden() and "TTS_KEY_NAME" not in _hidden()
        assert Redactor()(f"key {left} refused") == "key [redacted] refused"


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


def test_what_each_reader_reads_when_none_is_named_is_a_default_credential(tmp_path: Path) -> None:
    # Filled as the variables a configuration names are: each reader's own, none of a name.
    from types import SimpleNamespace

    from alphaavatar.agents.avatar.provider.factory import create_embedding_model, create_llm_model
    from alphaavatar.agents.configs.plugins.foundation.provider_config import ProviderTaskConfig
    from alphaavatar.host.configs.credentials import DEFAULT_CREDENTIALS
    from alphaavatar.plugins.deepresearch.tavily import TavilyDeepResearchTool
    from alphaavatar.plugins.provider.openai.llms.client import ResponsesClient
    from alphaavatar.plugins.provider.openai.llms.config import OpenAIClientConfig
    from alphaavatar.plugins.rag.rag_anything import RAGAnythingTool
    from alphaavatar.plugins.voice.stt.openai_realtime import OpenAIRealtimeSTT
    from alphaavatar.plugins.voice.stt.openai_segment import OpenAISegmentSTT
    from alphaavatar.plugins.voice.tts.openai import OpenAITTS
    from alphaavatar.plugins.voice.tts.voiceai import VoiceAITTS

    async def first_use(client) -> None:
        try:
            await (client.get() if isinstance(client, ResponsesClient) else client._model())
        finally:
            await client.aclose()

    def task(provider: str, kind: str = "llm") -> ProviderTaskConfig:
        return ProviderTaskConfig(kind=kind, provider=provider, model="m")

    readers = {
        "OPENAI_API_KEY": [
            lambda: asyncio.run(first_use(create_llm_model(task("openai")))),
            lambda: create_embedding_model(task("openai", "embedding")),
            lambda: asyncio.run(first_use(ResponsesClient(OpenAIClientConfig(), timeout=1))),
            lambda: OpenAITTS(model="speak", speaker="voice"),
            lambda: OpenAISegmentSTT(model="transcribe").stream(source_id="s"),
            lambda: OpenAIRealtimeSTT().stream(source_id="s"),
            lambda: asyncio.run(RAGAnythingTool(session_path=SimpleNamespace())._load()),
        ],
        "OPENROUTER_API_KEY": [
            lambda: asyncio.run(first_use(create_llm_model(task("openrouter"))))
        ],
        "ANTHROPIC_API_KEY": [lambda: asyncio.run(first_use(create_llm_model(task("anthropic"))))],
        "VOICEAI_API_KEY": [lambda: VoiceAITTS(model="speak")],
        "TAVILY_API_KEY": [lambda: TavilyDeepResearchTool(session_path=None)],
        "LIVEKIT_URL": [LiveKitCredentials.from_env],
    }
    with mock.patch.dict(os.environ, dict.fromkeys(DEFAULT_CREDENTIALS, "")):
        for name, made in readers.items():
            assert name in DEFAULT_CREDENTIALS
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
