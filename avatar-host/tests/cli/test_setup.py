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
"""`alphaavatar setup`, asked or given an existing bundle: refused early, or enabled only after
installing."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import signal
import stat
import sys
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import pytest
import yaml

# Imported at collection: the persona plugin's OpenCV adjusts process variables (O-2).
import alphaavatar.plugins.persona.factory  # noqa: F401
from alphaavatar.host.cli.app import main
from alphaavatar.host.tools.setup import environment
from alphaavatar.host.tools.setup.choices import (
    Selection,
    requirements,
    requirements_offered,
    sections,
)

CREDENTIALS = {
    "OPENAI_API_KEY": "sk-fictional-0042",
    "GOOGLE_API_KEY": "google-fictional-0042",  # ENV memory's, on as the reference has it.
    "LIVEKIT_URL": "wss://livekit.invalid",
    "LIVEKIT_API_KEY": "lk-fictional",
    "LIVEKIT_API_SECRET": "lk-fictional-secret",
}


def installed_plugins() -> dict[str, dict[str, str]]:
    """What installs each implementation, as the Linux build's catalog records it."""
    from importlib import metadata

    from alphaavatar.agents.runtime.plugin import AvatarModule
    from alphaavatar.host.configs.capabilities import with_extra

    found: dict[str, dict[str, str]] = {}
    for module in AvatarModule:
        for entry in metadata.entry_points(group=module.group):
            found.setdefault(module.value, {})[entry.name] = with_extra(entry.dist.name, entry.name)
    return found


def installed_modules() -> dict[str, dict[str, str]]:
    """The module each implementation's entry point names, as the Linux build's catalog records
    it."""
    from importlib import metadata

    from alphaavatar.agents.runtime.plugin import AvatarModule

    return {
        module.value: {entry.name: entry.module for entry in found}
        for module in AvatarModule
        if (found := metadata.entry_points(group=module.group))
    }


@pytest.fixture
def package(tmp_path: Path) -> environment.Installation:
    """An installed base whose catalog holds what any selection setup offers needs."""
    base = tmp_path / "prefix" / "versions" / "base-1"
    (base / "share" / "alphaavatar").mkdir(parents=True)
    offered = sorted(requirements_offered())
    names = sorted({text.split("[")[0] for text in offered})
    keys = {text: [text.split("[")[0]] for text in offered}
    keys |= {name: [name] for name in names}
    catalog = {
        "format": 1,
        "version": "1.0",
        "platform": "linux-x86_64",
        "base": [],
        "requirements": keys,
        # As a build's catalog: the implementations of the wheels it plans.
        "plugins": {
            module: {name: need for name, need in names.items() if need in keys}
            for module, names in installed_plugins().items()
        },
        "modules": installed_modules(),
        "distributions": {
            name: {
                "version": "1",
                "file": f"{name}.whl",
                "sha256": "0" * 64,
                "size": 1,
                "url": None,
            }
            for name in names
        },
    }
    (base / "share/alphaavatar/catalog.json").write_text(json.dumps(catalog))
    # A release's: its own wheels come from its assets unless --artifacts says otherwise.
    manifest = {"id": "base-1", "release": "v1.0"}
    (base / "share/alphaavatar/manifest.json").write_text(json.dumps(manifest))
    return environment.Installation(base.parent.parent, base)


def home_files() -> list[str]:
    home = Path.home() / ".local/share/alphaavatar"
    return sorted(str(p.relative_to(home)) for p in home.rglob("*")) if home.exists() else []


def test_setup_needs_a_package_and_a_terminal_or_a_bundle(capsys: pytest.CaptureFixture) -> None:
    assert main(["setup", "reference"]) == 1  # A checkout is no package.
    assert "setup installs into an AlphaAvatar package" in capsys.readouterr().err
    with mock.patch("sys.stdin.isatty", return_value=False):
        assert main(["setup"]) == 1
    assert "`alphaavatar setup <bundle>`" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["setup", "reference", "--name", "other"])  # Names belong to a new bundle.
    assert home_files() == []


def profile(name: str, section: str) -> Path:
    home = Path.home() / ".local/share/alphaavatar/configs/profiles"
    return next(home.glob(f"{name}/**/{section}.yaml"))


def edit(path: Path, *keys: str, value: object) -> None:
    body = yaml.safe_load(path.read_text())
    target = body
    for key in keys[:-1]:
        target = target.setdefault(key, {})
    target[keys[-1]] = value
    path.write_text(yaml.safe_dump(body))


def test_an_existing_bundle_is_planned_from_its_settings_and_refused_what_none_installs(
    package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    installed = mock.Mock(side_effect=AssertionError("nothing installs"))
    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch.object(environment, "install", installed),
        mock.patch("sys.stdin.isatty", return_value=False),
    ):
        assert main(["setup", "reference", "--plan"]) == 2
        refused = capsys.readouterr()
        assert "Bundle 'reference' does not exist" in refused.err
        # stdout stays JSON, why included, as upgrade reads the target's plan.
        assert "Bundle 'reference' does not exist" in json.loads(refused.out)["error"]["diagnostic"]
        assert main(["config", "init", "reference", "--avatar-id", "reference"]) == 0
        capsys.readouterr()
        # The plan alone changes nothing, and is the same plan each time.
        assert main(["setup", "reference", "--plan"]) == 0
        first = capsys.readouterr()
        assert main(["setup", "reference", "--plan"]) == 0
        assert json.loads(capsys.readouterr().out) == json.loads(first.out)
        assert json.loads(first.out)["requirements"] == list(requirements(Selection()))
        steps = (
            "01  Capabilities   Bundle reference · Voice on · Vision on · Local models on"
            " · ENV memory on\n"
        )
        assert steps in first.err
        before = home_files()
        # Edited, it is planned as edited: no face recognition, no package for it.
        edit(profile("reference", "persona"), "init_config", "face", "enabled", value=False)
        assert main(["setup", "reference", "--plan"]) == 0
        planned = json.loads(capsys.readouterr().out)["requirements"]
        assert planned == [
            r for r in requirements(Selection()) if r != "alpha-avatar-plugins-persona[face]"
        ]
        # A selection this release's setup has nothing for: refused before anything installs.
        edit(profile("reference", "tools"), "rag", "plugin", value="default")
        assert main(["setup", "reference"]) == 1
        refused = capsys.readouterr().err
        assert (
            "This release's setup installs nothing for: tools.rag.plugin: tools.rag 'default'"
            in refused
        )
    assert home_files() == before and not (package.prefix / "envs").exists()


@pytest.mark.parametrize(
    ("given", "why"),
    [
        ({}, "LIVEKIT_URL, LIVEKIT_API_KEY and LIVEKIT_API_SECRET are required"),
        (
            {"LIVEKIT_URL": "wss://lk.invalid"},
            "LIVEKIT_API_KEY and LIVEKIT_API_SECRET are required",
        ),
        (
            {**CREDENTIALS, "LIVEKIT_URL": "ws://lk.invalid"},
            "Remote LiveKit connections require TLS",
        ),
        # Credentials typed into the URL: as userinfo, as host and port (the parser quotes a
        # port it cannot read), in IPv6 brackets (it quotes what they hold).
        (
            {**CREDENTIALS, "LIVEKIT_URL": "wss://lk-fictional:lk-fictional-secret@lk.invalid"},
            "LiveKit URL must not contain credentials",
        ),
        ({**CREDENTIALS, "LIVEKIT_URL": "wss://lk-fictional:lk-fictional-secret"}, "not valid"),
        ({**CREDENTIALS, "LIVEKIT_URL": "wss://[lk-fictional-secret]:7880"}, "not valid"),
    ],
    ids=["none", "no key", "no TLS", "userinfo", "port", "IPv6"],
)
def test_an_existing_bundle_is_refused_before_installing_without_its_session_credentials(
    package: environment.Installation,
    capsys: pytest.CaptureFixture,
    caplog: pytest.LogCaptureFixture,
    given: dict,
    why: str,
) -> None:
    assert main(["config", "init", "reference", "--avatar-id", "reference"]) == 0
    capsys.readouterr()
    before = home_files()
    environ = {k: v for k, v in os.environ.items() if not k.startswith("LIVEKIT_")} | given
    caplog.set_level(logging.DEBUG)
    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch("sys.stdin.isatty", return_value=False),
        mock.patch.dict(os.environ, environ, clear=True),
        mock.patch.object(environment, "install") as install,
    ):
        assert main(["setup", "reference", "--artifacts", "/ci/run"]) == 1
    output = capsys.readouterr()
    assert not install.called and home_files() == before  # Nothing installed nor enabled.
    assert "The session transport (livekit) cannot start: " in output.err and why in output.err
    # Named, never shown: not on either stream, not in a log record.
    assert "lk-fictional" not in output.err + output.out + caplog.text


@pytest.mark.parametrize(
    "setting", ["api_secret", "connect_timeout"], ids=["unknown key", "wrong type"]
)
def test_a_session_setting_the_transport_refuses_is_named_never_shown(
    package: environment.Installation,
    capsys: pytest.CaptureFixture,
    caplog: pytest.LogCaptureFixture,
    setting: str,
) -> None:
    # A secret written into the bundle's transport settings, where no credential belongs, or
    # as a value of the wrong type: the validator quotes either; setup names the field only.
    assert main(["config", "init", "reference", "--avatar-id", "reference"]) == 0
    edit(profile("reference", "host"), "rtc", "init_config", setting, value="TEST_CONFIG_SECRET")
    capsys.readouterr()
    before = home_files()
    caplog.set_level(logging.DEBUG)
    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch("sys.stdin.isatty", return_value=False),
        mock.patch.dict(os.environ, CREDENTIALS),
        mock.patch.object(environment, "install") as install,
    ):
        assert main(["setup", "reference", "--artifacts", "/ci/run"]) == 1
    output = capsys.readouterr()
    assert not install.called and home_files() == before  # Nothing installed nor enabled.
    assert "The session transport (livekit) cannot start: " in output.err
    assert f"host.rtc.init_config.{setting}" in output.err
    assert "TEST_CONFIG_SECRET" not in output.err + output.out + caplog.text


def test_an_existing_bundle_with_an_stt_plugin_and_no_model_is_refused_before_installing(
    package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    # Refused as it validates, at the field, as config check, Doctor and start refuse it (O-10).
    assert main(["config", "init", "reference", "--avatar-id", "reference"]) == 0
    edit(profile("reference", "voice"), "stt", "model", value=" ")
    capsys.readouterr()
    before = home_files()
    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch("sys.stdin.isatty", return_value=False),
        mock.patch.dict(os.environ, CREDENTIALS),
        mock.patch.object(environment, "install") as install,
    ):
        assert main(["setup", "reference", "--artifacts", "/ci/run"]) == 2
    output = capsys.readouterr()
    assert not install.called and home_files() == before  # Nothing installed nor enabled.
    assert "Setup failed; nothing was enabled" in output.err
    assert "fields: voice.stt.model" in output.err


def test_typed_session_credentials_are_checked_before_anything_is_stored_or_installed(
    package: environment.Installation,
    capsys: pytest.CaptureFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The key and secret typed as the URL, as a host and a port: the values that take
    # effect, typed over what the environment holds, are the ones checked.
    person = Person(
        ("Bundle name", "second"),
        ("OPENAI_API_KEY, for", "sk-new"),
        ("LIVEKIT_URL, for", "wss://lk-key:lk-fictional-secret"),
        ("LIVEKIT_API_KEY, for", "lk-key"),
        ("LIVEKIT_API_SECRET, for", "lk-fictional-secret"),
    )
    caplog.set_level(logging.DEBUG)
    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch.object(environment, "install") as install,
        mock.patch("sys.stdin.isatty", return_value=True),
        mock.patch.dict(os.environ, CREDENTIALS),
        person.answering(),
    ):
        assert main(["setup"]) == 1
    assert person.rules == []
    output = capsys.readouterr()
    assert "The session transport (livekit) cannot start: LiveKit URL is not valid" in output.err
    assert "as typed or in the environment" in output.err
    assert "lk-fictional-secret" not in output.err + output.out + caplog.text
    assert "Store " not in output.out  # Refused before the question to store them.
    assert not install.called and home_files() == []  # Nothing stored, nothing written.


def test_an_existing_bundle_is_enabled_only_by_a_successful_install(
    package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    assert main(["config", "init", "earlier", "--avatar-id", "earlier"]) == 0
    assert main(["config", "init", "reference", "--avatar-id", "reference"]) == 0
    capsys.readouterr()
    # Edited as a person edits it: setup installs for it as it is, never resetting it.
    edit(profile("reference", "voice"), "tts", "speed", value=1.3)
    before = home_files()
    home = Path.home() / ".local/share/alphaavatar"
    configs = {p: p.read_bytes() for p in (home / "configs").rglob("*") if p.is_file()}

    def default() -> str:
        return yaml.safe_load((home / "settings/settings.yaml").read_text())["default_bundle"]

    def failed(*args, check, enable, **kwargs):
        raise environment.SetupError("the environment fails its check")

    def installed(installation, plan, sources, *, check, enable, **kwargs):
        assert sources == environment.Sources("/ci/run", "v1.0")
        enable()
        return installation.environment(plan)

    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch("sys.stdin.isatty", return_value=False),
        mock.patch.dict(os.environ, CREDENTIALS),  # As CI exports them
    ):
        with mock.patch.object(environment, "install", failed):
            assert main(["setup", "reference", "--artifacts", "/ci/run"]) == 1
        output = capsys.readouterr()
        assert "nothing was enabled" in output.err
        assert "Bundle enabled" not in output.out  # Said only once checked and enabled.
        assert (home_files(), default()) == (before, "earlier")
        with mock.patch.object(environment, "install", installed):
            assert main(["setup", "reference", "--artifacts", "/ci/run"]) == 0
    assert default() == "reference"  # Enabled: the default now.
    assert {p: p.read_bytes() for p in (home / "configs").rglob("*") if p.is_file()} == configs
    # The environment's credentials stay there: nothing stores them.
    assert "credentials" not in yaml.safe_load((home / "settings/settings.yaml").read_text())
    assert not [path.name for path in (home / "settings").iterdir() if "credentials" in path.name]
    shown = capsys.readouterr().out.splitlines()
    assert "02  Models         As the bundle's settings choose them" in shown
    assert "03  Credentials    From the environment, .env or those stored" in shown
    assert shown[-4:] == ["", "Next", "  alphaavatar doctor reference", ""]


class Person:
    """A person at the terminal: each question answered by what it asks, the first rule whose
    text the prompt holds taken once, in order; any other answered with Enter, its default.
    Each prompt is kept, and shown as input() shows it."""

    def __init__(self, *rules: tuple[str, str | type[BaseException]]) -> None:
        self.rules = list(rules)
        self.prompts: list[str] = []

    def __call__(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        sys.stdout.write(prompt)
        for index, (asked, answer) in enumerate(self.rules):
            if asked in prompt:
                del self.rules[index]
                if isinstance(answer, type):
                    raise answer
                return answer
        return ""

    def asked(self, text: str) -> list[str]:
        return [prompt for prompt in self.prompts if text in prompt]

    @contextlib.contextmanager
    def answering(self) -> Iterator[Person]:
        # Wide: each question is one prompt, as the rules read them, never wrapped.
        with (
            mock.patch("builtins.input", self),
            mock.patch("getpass.getpass", self),
            mock.patch.dict(os.environ, {"COLUMNS": "1000"}),
        ):
            yield self


TYPED = (
    ("OPENAI_API_KEY, for", "sk-new"),
    ("GOOGLE_API_KEY, for", "google-new"),
    ("LIVEKIT_URL, for", "wss://livekit.invalid"),
    ("LIVEKIT_API_KEY, for", "lk-key"),
    ("LIVEKIT_API_SECRET, for", "lk-secret"),
)


def test_the_plan_alone_goes_to_stdout_even_when_setup_asks(
    package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    # Voice, vision, no local models, ENV memory, LanceDB; the name; then Enter: each default.
    # Asked on stderr, the prompt is shown there before input() reads: answered in order.
    queue = ["", "", "n", "", "", "remote"]

    def typed(prompt: str = "") -> str:
        sys.stdout.write(prompt)  # As input() shows its prompt.
        return queue.pop(0) if queue else ""

    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch("sys.stdin.isatty", return_value=True),
        mock.patch("builtins.input", typed),
    ):
        assert main(["setup", "--plan"]) == 0
    output = capsys.readouterr()
    planned = json.loads(output.out)["requirements"]
    assert planned == list(requirements(Selection(local_models=False)))
    # The step and its questions went to stderr: stdout is the plan for a tool to read.
    assert "Each question starts from the reference configuration" in output.err
    assert "Provider for the conversation [1]: " in output.err
    # (Answered here without a terminal's echo, so a prompt and the next line share one.)
    assert (
        "01  Capabilities   Bundle remote · Voice on · Vision on · Local models off · ENV memory on\n"
        in output.err
    )
    assert "02  Models         OpenAI · Google\n" in output.err
    assert queue == [] and output.out.count("Provider for") == 0
    assert home_files() == []


def test_a_plan_declined_installs_and_enables_nothing(
    package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    installed = mock.Mock(side_effect=AssertionError("nothing installs"))
    # No local models, its name, the credentials set already, not stored; then no.
    person = Person(
        ("Models on this machine", "n"),
        ("Bundle name", "remote"),
        ("Store ", "n"),
        ("Install and enable?", "n"),
    )
    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch.object(environment, "install", installed),
        mock.patch("sys.stdin.isatty", return_value=True),
        mock.patch.dict(os.environ, CREDENTIALS),
        person.answering(),
    ):
        assert main(["setup"]) == 1
    output = capsys.readouterr()
    # The plan and what it downloads were shown before the question; then nothing changed.
    assert re.search(r"\n      Packages +\d+\n      Download +0 MB\n", output.out)
    assert person.rules == []
    assert output.err == "WARN  Cancelled; nothing was enabled\n\n"
    assert home_files() == []


@pytest.mark.parametrize(
    ("question", "stop", "code", "said"),
    [
        ("Bundle name [avatar]: ", KeyboardInterrupt, 130, "Interrupted"),
        ("Provider for memory [2]: ", KeyboardInterrupt, 130, "Interrupted"),
        ("Model for the conversation [gpt-5.6-luna]: ", EOFError, 1, "The input ended"),
    ],
    ids=["a-name", "a-provider", "the-input-ending"],
)
def test_ctrl_c_or_the_input_ending_at_a_question_enables_nothing_and_says_so(
    package: environment.Installation,
    capsys: pytest.CaptureFixture,
    question: str,
    stop: type[BaseException],
    code: int,
    said: str,
) -> None:
    person = Person((question.strip(), stop))  # Each other part as the reference has it.
    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch("sys.stdin.isatty", return_value=True),
        person.answering(),
    ):
        assert main(["setup"]) == code
    output = capsys.readouterr()
    assert output.err == f"WARN  {said}; nothing was enabled\n\n"
    # The question's line ends, then a blank line: the outcome stands apart from the steps.
    assert output.out.endswith(f"{question}\n\n") and person.rules == []
    assert home_files() == []


def test_asked_credentials_are_stored_on_a_yes_and_a_stored_one_replaced_only_on_another(
    package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    from alphaavatar.host.configs import application_paths
    from alphaavatar.host.configs.credentials import credentials_path
    from alphaavatar.host.configs.template import create_bundle

    paths = application_paths()
    earlier = {"OPENAI_API_KEY": "sk-earlier"}
    create_bundle(paths, "first", avatar_id="first", make_default=True, credentials=earlier)

    def installed(installation, plan, sources, *, check, enable, **kwargs):
        enable()
        return installation.environment(plan)

    person = Person(
        ("Bundle name", "second"),
        *TYPED,
        ("Store ", "y"),
        ("OPENAI_API_KEY is stored already", "n"),
        ("Install and enable?", "y"),
    )
    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch.object(environment, "install", installed),
        mock.patch("sys.stdin.isatty", return_value=True),
        mock.patch.dict(os.environ),
        person.answering(),
    ):
        assert main(["setup"]) == 0
    assert person.rules == []
    output = capsys.readouterr().out
    stored = credentials_path(paths).read_text()
    # The earlier bundle's key stays; what was new is stored, readable only by the person.
    assert 'OPENAI_API_KEY="sk-earlier"' in stored and "sk-new" not in stored
    assert 'LIVEKIT_API_SECRET="lk-secret"' in stored
    assert stat.S_IMODE(credentials_path(paths).stat().st_mode) == 0o600
    assert "OPENAI_API_KEY stays as stored" in output and "sk-new" not in output


def test_env_memory_switched_off_asks_no_google_key_and_keeps_its_settings_to_switch_on(
    package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    # Each part as the reference has it but ENV memory; then the name, the credentials the
    # environment holds (Enter keeps them), not stored, and yes to installing.
    person = Person(
        ("ENV memory:", "n"),
        ("Bundle name", "quiet"),
        ("Store ", "n"),
        ("Install and enable?", "y"),
    )

    def installed(installation, plan, sources, *, check, enable, **kwargs):
        enable()
        return installation.environment(plan)

    without = {name: value for name, value in CREDENTIALS.items() if name != "GOOGLE_API_KEY"}
    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch.object(environment, "install", installed),
        mock.patch("sys.stdin.isatty", return_value=True),
        mock.patch.dict(os.environ, without | {"COLUMNS": "1000"}),
        person.answering(),
    ):
        assert main(["setup"]) == 0
    # Off, it asks nothing of its own: no model, no Google key.
    assert person.rules == [] and person.asked("GOOGLE_API_KEY") == []
    assert person.asked("ENV memory") == [person.prompts[3]] and person.asked("Model for") != []
    assert "ENV memory off" in capsys.readouterr().out
    memory = Path.home() / ".local/share/alphaavatar/configs/profiles/quiet/plugins/perception"
    text = (memory / "memory.yaml").read_text()
    # Off, its settings and the comments on them kept: switched on, it runs as the reference.
    assert "  environment:\n    enabled: false\n    include_audio: true\n" in text
    assert "# Memories drawn from the session's audio and video by Google's Gemini" in text
    assert "            provider: google\n            model: gemini-2.5-flash\n" in text


def test_a_key_stored_for_one_server_of_ones_own_serves_no_other(
    package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    from alphaavatar.host.configs import application_paths, load_application, select_configuration
    from alphaavatar.host.configs.credentials import stored_credentials
    from alphaavatar.host.tools.setup.choices import server_key

    a, b = "http://a.invalid:8000/v1", "http://b.invalid:8000/v1"
    prompts: list[str] = []

    def installed(installation, plan, sources, *, check, enable, **kwargs):
        enable()
        return installation.environment(plan)

    def setup(name: str, server: str, key: str, *, store: str | None, install: bool = True) -> int:
        # No voice, no local models; each model from `server`, the conversation's taken for
        # memory and persona; then the server's key, Google's and LiveKit's (Enter keeps them).
        person = Person(
            ("Voice:", "n"),
            ("Models on this machine", "n"),
            ("Bundle name", name),
            ("Provider for the conversation", "2"),
            ("Server URL for the conversation", server),
            ("Model for the conversation", "chat"),
            ("Provider for memory", "1"),
            ("Provider for tool memory", "1"),
            ("Provider for persona profiles", "1"),
            ("Provider for embeddings", "3"),
            ("Model for embeddings", "embed"),
            (server_key(server), key),
            *((("Store ", store),) if store is not None else ()),
            *((("Install and enable?", "y"),) if install else ()),
        )

        livekit = {
            "GOOGLE_API_KEY": "google-fictional-0042",
            "LIVEKIT_URL": "wss://lk.invalid",
            "LIVEKIT_API_KEY": "k",
            "LIVEKIT_API_SECRET": "s",
        }
        with (
            mock.patch.object(environment.Installation, "running", return_value=package),
            mock.patch.object(environment, "install", installed),
            mock.patch("sys.stdin.isatty", return_value=True),
            # Wide: each question is one prompt, as this test reads them, the parts a server's
            # key serves included.
            mock.patch.dict(os.environ, livekit | {"COLUMNS": "1000"}),
            person.answering(),
        ):
            code = main(["setup"])
        prompts.extend(person.prompts)
        assert person.rules == []
        # The embeddings' server question offered the server typed before.
        assert person.asked(f"Server URL for embeddings [{server}]: ") != []
        return code

    def asked(server: str) -> str:
        return next(p for p in reversed(prompts) if p.strip().startswith(server_key(server)))

    paths = application_paths()
    assert setup("first", a, "key-a", store="y") == 0
    # Another server's key is not this one's, nor is a blank set for it: Enter keeps nothing,
    # and the key is missing.
    with mock.patch.dict(os.environ, {server_key(b): " \t"}):
        assert setup("second", b, "", store=None, install=False) == 1
    assert "Enter keeps" not in asked(b)
    assert f"Missing credentials: {server_key(b)}" in capsys.readouterr().err
    assert stored_credentials(paths)[server_key(a)] == "key-a"
    # Blank in the environment but in the .env file start reads, the bundle's key is set.
    dotenv = Path("b.env")
    dotenv.write_text(f"{server_key(b)}=key-b-file\n")
    with mock.patch.dict(os.environ, {server_key(b): " \t", "ENV_FILE": str(dotenv.resolve())}):
        assert setup("from-file", b, "", store="n") == 0  # Not stored; enabled.
    assert "Enter keeps it" in asked(b) and server_key(b) not in stored_credentials(paths)
    # Storing the other server's key leaves the first server's, which the first bundle reads.
    assert setup("third", b, "key-b", store="y") == 0
    stored = stored_credentials(paths)
    assert (stored[server_key(a)], stored[server_key(b)]) == ("key-a", "key-b")
    first = load_application(select_configuration("first")).avatar.loop.init_config["model"]
    assert first["extra"] == {"base_url": a, "api_key_env": server_key(a)}
    # The same server again: its stored key serves it, kept with Enter.
    assert setup("fourth", a, "", store=None) == 0
    assert "Enter keeps it" in asked(a)
    assert stored_credentials(paths)[server_key(a)] == "key-a"


def test_a_new_bundle_keeps_what_the_current_environment_holds(
    package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    current = package.prefix / "envs" / "installed"
    (current / environment.PLAN_FILE).parent.mkdir(parents=True)
    os.symlink("envs/installed", package.prefix / "current")
    installed = {"base": "base-1", "requirements": list(requirements(Selection()))}
    (current / environment.PLAN_FILE).write_text(json.dumps(installed))
    from alphaavatar.host.configs import application_paths
    from alphaavatar.host.configs.template import create_bundle

    remote = Selection(local_models=False)
    create_bundle(application_paths(), "remote", avatar_id="remote", sections=sections(remote))

    def plan() -> list[str]:
        assert main(["setup", "remote", "--plan"]) == 0
        return json.loads(capsys.readouterr().out)["requirements"]

    with mock.patch.object(environment.Installation, "running", return_value=package):
        # A bundle with no local model alone would drop the reference's models; they stay.
        assert plan() == installed["requirements"]
        # An environment over another base is not this version's to keep.
        (current / environment.PLAN_FILE).write_text(json.dumps(installed | {"base": "base-0"}))
        assert plan() == list(requirements(remote))


@pytest.mark.parametrize(
    ("replaced", "then"),
    [("credentials", "SIGTERM"), ("settings.yaml", "SIGTERM"), ("settings.yaml", "OSError")],
)
def test_what_ends_enabling_leaves_current_the_bundle_and_credentials_agreeing(
    package: environment.Installation, capsys: pytest.CaptureFixture, replaced: str, then: str
) -> None:
    from alphaavatar.host.configs import application_paths, credentials as stored
    from alphaavatar.host.configs.credentials import credentials_path

    # The base holds everything the plan needs: a real, empty environment installs.
    path = package.base / "share/alphaavatar/catalog.json"
    catalog = json.loads(path.read_text())
    path.write_text(json.dumps(catalog | {"base": sorted(catalog["distributions"])}))
    (package.base / "python/bin").mkdir(parents=True)
    (package.base / "python/bin/python3").symlink_to(sys._base_executable)
    os.symlink("versions/base-1", package.prefix / "current")
    replace, write = os.replace, stored.write_credentials

    def replacing(source: object, target: object) -> None:
        replace(source, target)
        if Path(target).name == replaced:  # Right after the replacement.
            if then == "OSError":
                raise OSError("the settings lock cannot be released")
            os.kill(os.getpid(), signal.SIGTERM)

    def writing(*args: object) -> Path:
        written = write(*args)
        if replaced == "credentials":  # Right after the new credentials are written.
            os.kill(os.getpid(), signal.SIGTERM)
        return written

    person = Person(
        ("Bundle name", "second"), *TYPED, ("Store ", "y"), ("Install and enable?", "y")
    )
    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch.object(environment, "check_environment", lambda *args: None),
        mock.patch.object(os, "replace", replacing),
        mock.patch.object(stored, "write_credentials", writing),
        mock.patch("sys.stdin.isatty", return_value=True),
        mock.patch.dict(os.environ),
        person.answering(),
    ):
        assert main(["setup"]) == (0 if then == "OSError" else 128 + signal.SIGTERM)
    if then == "SIGTERM":
        assert "WARN  Stopped; bundle second was enabled first\n" in capsys.readouterr().err
    # All of it new: current, the default bundle and the credentials it reads.
    assert os.readlink(package.prefix / "current").startswith("envs/")
    home = Path.home() / ".local/share/alphaavatar"
    assert (
        yaml.safe_load((home / "settings/settings.yaml").read_text())["default_bundle"] == "second"
    )
    assert 'LIVEKIT_API_SECRET="lk-secret"' in credentials_path(application_paths()).read_text()


def enabled(installation, plan, sources, *, check, enable, **kwargs):
    enable()
    return installation.environment(plan)


def test_each_part_is_asked_its_provider_then_its_model_and_each_key_once(
    package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    from alphaavatar.host.configs import load_application, select_configuration

    # Without a terminal to redraw, each list is numbered: answered here by the text of one.
    person = Person(
        ("Bundle name", "mixed"),
        ("Provider for memory", "anthropic"),
        ("Model for memory", "claude-sonnet-4-5"),
        ("Provider for tool memory", "as for memory"),
        ("Provider for persona profiles", "openrouter"),
        ("Model for persona profiles", "openai/gpt-4.1-mini"),
        ("Provider for embeddings", "google"),
        ("Model for embeddings", "text-embedding-004"),
        ("Provider for speech recognition", "realtime"),
        ("Model for speech recognition", "gpt-realtime-whisper"),
        ("Provider for speech synthesis", "voice.ai"),
        ("Model for speech synthesis", "voiceai-tts-v1"),
        ("ANTHROPIC_API_KEY, for", "ant-fictional"),
        ("OPENROUTER_API_KEY, for", "or-fictional"),
        ("VOICEAI_API_KEY, for", "vai-fictional"),
        ("Store ", "n"),
        ("Install and enable?", "y"),
    )
    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch.object(environment, "install", enabled),
        mock.patch("sys.stdin.isatty", return_value=True),
        mock.patch.dict(os.environ, CREDENTIALS),
        person.answering(),
    ):
        assert main(["setup"]) == 0
    out = capsys.readouterr().out
    assert person.rules == []
    # The reference's model is offered from its own provider only; from another, none is.
    assert person.asked("Model for the conversation [gpt-5.6-luna]: ") != []
    for part in ("memory", "persona profiles", "embeddings", "speech recognition"):
        assert person.asked(f"Model for {part}: ") != [], part
    # Voice.ai takes no speed and needs no voice: neither is asked for.
    assert person.asked("Speed") == [] and person.asked("  Voice [") == []
    # Each key once, naming every part that reads it.
    keys = [p.split(",")[0].strip() for p in person.prompts if "_API_KEY, for" in p]
    assert sorted(keys) == sorted(set(keys)) and "ANTHROPIC_API_KEY" in keys
    assert person.asked("ANTHROPIC_API_KEY, for memory, tool memory, from Anthropic") != []
    assert person.asked("GOOGLE_API_KEY, for ENV memory, embeddings, from Google") != []
    assert "02  Models         OpenAI · Anthropic · Google · OpenRouter · Voice.ai\n" in out
    # The summary, after the questions and before anything is installed.
    summary = "      Memory          Anthropic    claude-sonnet-4-5\n"
    assert out.index("03  Credentials    Ready") < out.index(summary) < out.index("Install and")
    assert "      Tool memory     Anthropic    claude-sonnet-4-5\n" in out
    assert "      Persona         OpenRouter   openai/gpt-4.1-mini\n" in out
    assert "      TTS             voiceai · voiceai-tts-v1 · no instructions\n" in out
    assert "      Voice / Speed   the model's own · 1.0 (fixed)\n" in out
    assert "fictional" not in out
    # The bundle runs as answered.
    avatar = load_application(select_configuration("mixed")).avatar
    tasks = {
        part: avatar.memory.init_config[part]["provider"]["gateway"]["tasks"]
        for part in ("conversation", "tool")
    }
    assert tasks["conversation"]["memory.conversation_delta"]["provider"] == "anthropic"
    assert tasks["tool"]["memory.tool_delta"]["model"] == "claude-sonnet-4-5"
    profiler = avatar.persona.init_config["profiler"]["provider"]["gateway"]["tasks"]
    assert profiler["persona.profile_delta"]["provider"] == "openrouter"
    assert avatar.memory.vdb_config["embedding"]["provider"] == "google"
    assert (avatar.voice.stt.plugin, avatar.voice.stt.model) == (
        "openai_realtime",
        "gpt-realtime-whisper",
    )
    tts = avatar.voice.tts
    assert (tts.plugin, tts.speaker, tts.speed, tts.instructions) == ("voiceai", None, 1.0, None)


def test_an_existing_bundle_s_summary_shows_its_own_settings_before_it_installs(
    package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    """An existing bundle, set up on a terminal: its tools on, its conversation on a server of
    its own whose URL holds a credential, memory's vectors in Qdrant. The summary shows each as
    set, the server's address without its credential, query or fragment, and the bundle as the
    default it is already; then the question."""
    assert main(["config", "init", "tooled", "--avatar-id", "tooled-id"]) == 0
    capsys.readouterr()
    # The tools a build's catalog installs, as a release's has them.
    path = package.base / "share/alphaavatar/catalog.json"
    catalog = json.loads(path.read_text())
    for module, name in (("tools.deepresearch", "deepresearch"), ("tools.mcp", "mcp")):
        need = f"alpha-avatar-plugins-{name}"
        catalog["requirements"][need] = [need]
        artifact = {"version": "1", "file": f"{need}.whl", "sha256": "0" * 64, "size": 1}
        catalog["distributions"][need] = artifact | {"url": None}
        catalog["plugins"][module] = {"default": need}
    path.write_text(json.dumps(catalog))
    tools = profile("tooled", "tools")
    edit(tools, "deepresearch", "plugin", value="default")
    edit(tools, "mcp", "enabled", value=True)
    edit(tools, "mcp", "servers", value={"docs": {"url": "https://mcp.invalid/"}})
    server = "https://person:hidden-pass@gpu.invalid:8000/v1?token=hidden-token#hidden-part"
    extra = {"base_url": server, "api_key_env": "MY_GPU_KEY"}
    edit(profile("tooled", "loop"), "init_config", "model", "extra", value=extra)
    edit(profile("tooled", "memory"), "vdb_config", "url", value="https://qdrant.invalid:6333")
    person = Person(("Install and enable?", "y"))
    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch.object(environment, "install", enabled),
        mock.patch("sys.stdin.isatty", return_value=True),
        mock.patch.dict(os.environ, CREDENTIALS | {"MY_GPU_KEY": "gpu-fictional"}),
        person.answering(),
    ):
        assert main(["setup", "tooled"]) == 0
    out = capsys.readouterr().out
    assert person.rules == []
    summary = out[out.index("04  Install") : out.index("Install and enable?")]
    for line in (
        "\n    Configuration\n      Bundle          tooled · already the default\n",
        "      Avatar ID       tooled-id\n",
        "      Conversation    Your server  gpt-5.6-luna · https://gpu.invalid:8000/v1\n",
        "      Vectors         Memory: Qdrant · https://qdrant.invalid:6333\n"
        "                      Persona: LanceDB · Avatar workspace\n",
        "      Tools           DeepResearch (default) · MCP (default, 1 server)\n",
    ):
        assert line in summary, line
    assert "hidden" not in out and "None enabled" not in summary


def _summary_of(
    package,
    capsys,
    name: str,
    *edits: tuple[str, tuple[str, ...], object],
    environ: dict[str, str] | None = None,
) -> str:
    """The install summary of the bundle ``name``, config init's with ``edits`` (a section,
    the keys to a setting, its value) made as a person makes them, set up on a terminal with
    ``environ`` beside the credentials."""
    assert main(["config", "init", name, "--avatar-id", name]) == 0
    capsys.readouterr()
    for section, keys, value in edits:
        edit(profile(name, section), *keys, value=value)
    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch.object(environment, "install", enabled),
        mock.patch("sys.stdin.isatty", return_value=True),
        mock.patch.dict(os.environ, CREDENTIALS | (environ or {})),
        Person(("Install and enable?", "y")).answering(),
    ):
        assert main(["setup", name]) == 0
    out = capsys.readouterr().out
    return out[out.index("04  Install") : out.index("Install and enable?")]


ANTHROPIC = {"provider": "anthropic", "model": "claude-sonnet-4-5"}
CONVERSATION = ("init_config", "conversation", "provider")
PROFILER = ("init_config", "profiler", "provider")


@pytest.mark.parametrize("default", ["kept", "deleted"])
def test_an_existing_bundle_s_summary_shows_the_task_each_processor_selects(
    default: str, package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    """Memory's conversation and persona's profiler naming tasks of their own, beside the
    default ones or in their place: the summary shows the models those tasks name, as start
    runs them, never the default tasks'."""
    tasks = {"my.memory": ANTHROPIC}
    profiles = {"my.profile": {"provider": "google", "model": "gemini-2.5-flash"}}
    if default == "kept":
        tasks |= {"memory.conversation_delta": {"provider": "openai", "model": "gpt-4o"}}
        profiles |= {"persona.profile_delta": {"provider": "openai", "model": "gpt-4o"}}
    summary = _summary_of(
        package,
        capsys,
        "tasked",
        ("memory", (*CONVERSATION, "task"), "my.memory"),
        ("memory", (*CONVERSATION, "gateway", "tasks"), tasks),
        ("persona", (*PROFILER, "profile_delta_task"), "my.profile"),
        ("persona", (*PROFILER, "gateway", "tasks"), profiles),
    )
    assert "      Memory          Anthropic    claude-sonnet-4-5\n" in summary
    assert "      Persona         Google       gemini-2.5-flash\n" in summary
    assert "      Tool memory     OpenAI       gpt-4o\n" in summary  # As its own task names.


@pytest.mark.parametrize(
    ("section", "processor", "label"),
    [
        ("memory", "conversation", "Memory"),
        ("memory", "tool", "Tool memory"),
        ("persona", "profiler", "Persona"),
    ],
)
def test_an_existing_bundle_s_summary_shows_a_processor_switched_off_as_off(
    section: str,
    processor: str,
    label: str,
    package: environment.Installation,
    capsys: pytest.CaptureFixture,
) -> None:
    """A processor switched off runs no model: shown off, with the model its settings keep
    for it; its settings as they were."""
    summary = _summary_of(
        package, capsys, "quiet", (section, ("init_config", processor, "enabled"), False)
    )
    assert f"      {label.ljust(16)}Off          configured: OpenAI gpt-4o\n" in summary
    others = {"Memory", "Tool memory", "Persona"} - {label}
    for other in others:
        assert f"      {other.ljust(16)}OpenAI       gpt-4o\n" in summary, other
    path = profile("quiet", section)
    assert yaml.safe_load(path.read_text())["init_config"][processor]["enabled"] is False


@pytest.mark.parametrize("value", ["true", "false"])
def test_an_existing_bundle_s_switches_read_from_the_environment_are_read_as_start_reads_them(
    value: str, package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    """Memory's conversation and ENV memory switched by variables: the strings interpolation
    leaves read as their plugin's schema reads them, the capability and its model's row
    agreeing."""
    on = value == "true"
    summary = _summary_of(
        package,
        capsys,
        "switched",
        ("memory", ("init_config", "conversation", "enabled"), "${oc.env:MEMORY_EXTRACTION_ON}"),
        ("memory", ("init_config", "environment", "enabled"), "${oc.env:ENV_MEMORY_ON}"),
        environ={"MEMORY_EXTRACTION_ON": value, "ENV_MEMORY_ON": value},
    )
    memory = "OpenAI       gpt-4o" if on else "Off          configured: OpenAI gpt-4o"
    assert f"      Memory          {memory}\n" in summary
    assert f"      ENV memory      {'On' if on else 'Off'}\n" in summary
    env = (
        "Google       gemini-2.5-flash"
        if on
        else "Off          configured: Google gemini-2.5-flash"
    )
    assert f"      ENV memory      {env}\n" in summary


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        (True, "OpenAI       gpt-4o"),
        (False, "Off          configured: OpenAI gpt-4o"),
        ("yes", "OpenAI       gpt-4o"),
        ("off", "Off          configured: OpenAI gpt-4o"),
        (1, "OpenAI       gpt-4o"),
        (0, "Off          configured: OpenAI gpt-4o"),
        ("maybe", "Not told: its switch 'maybe' is not true or false"),
    ],
    ids=["true", "false", "yes", "off", "one", "zero", "invalid"],
)
def test_an_existing_bundle_s_switch_is_read_in_each_form_its_schema_takes(
    value: object, shown: str, package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    """A switch written as a bool, a word or a number reads as the schema reads it; one the
    schema refuses is said so, never shown off."""
    summary = _summary_of(
        package, capsys, "forms", ("memory", ("init_config", "tool", "enabled"), value)
    )
    assert f"      Tool memory     {shown}\n" in summary


@pytest.mark.parametrize("same", [False, True], ids=["apart", "together"])
def test_an_existing_bundle_s_summary_shows_each_store_s_embedding(
    same: bool, package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    """Memory, persona and MCP each with the embedding its settings name: one row where they
    are one, else a line each, with the stores that use it."""
    google = {"provider": "google", "model": "text-embedding-004"}
    edits = [
        ("tools", ("mcp", "enabled"), True),
        ("tools", ("mcp", "servers"), {"docs": {"url": "https://mcp.invalid/"}}),
    ]
    if not same:
        edits.append(("persona", ("vdb_config", "embedding"), google))
    path = package.base / "share/alphaavatar/catalog.json"
    catalog = json.loads(path.read_text())
    need = "alpha-avatar-plugins-mcp"
    catalog["requirements"][need] = [need]
    artifact = {"version": "1", "file": f"{need}.whl", "sha256": "0" * 64, "size": 1}
    catalog["distributions"][need] = artifact | {"url": None}
    catalog["plugins"]["tools.mcp"] = {"default": need}
    path.write_text(json.dumps(catalog))
    summary = _summary_of(package, capsys, "stores", *edits)
    if same:
        assert "      Embedding       OpenAI       text-embedding-3-small\n" in summary
    else:
        assert (
            "      Embedding       OpenAI       text-embedding-3-small · memory, MCP\n"
            "                      Google       text-embedding-004 · persona\n"
        ) in summary


def test_voice_off_asks_nothing_of_speech_and_vectors_in_qdrant_read_its_url(
    package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    profiles = Path.home() / ".local/share/alphaavatar/configs/profiles"
    url = "https://qdrant.invalid:6333"

    def setup(name: str, *typed: tuple[str, str]) -> Person:
        person = Person(
            ("Voice:", "n"),
            ("Vectors for memory and persona", "2"),
            ("Bundle name", name),
            *typed,
            ("Store ", "n"),
            ("Install and enable?", "y"),
        )
        with (
            mock.patch.object(environment.Installation, "running", return_value=package),
            mock.patch.object(environment, "install", enabled),
            mock.patch("sys.stdin.isatty", return_value=True),
            mock.patch.dict(os.environ, CREDENTIALS),
            person.answering(),
        ):
            os.environ.pop("QDRANT_URL", None)
            assert main(["setup"]) == 0
        assert person.rules == []
        return person

    # Asked with the other credentials, before anything resolves the bundle that reads it.
    person = setup("vectors", ("QDRANT_URL, for", url))
    out = capsys.readouterr().out
    # Step 01's note of the tools: none on, how to switch one on; no fault.
    assert (
        "    Tools  None enabled (default)\n"
        "           Enable DeepResearch or MCP in the tools profile,\n"
        "           then run: alphaavatar setup <bundle>\n"
        "           RAG is not available through setup in this release.\n"
    ) in out
    # The summary: voice off, so no speech; the vectors in the server the URL names.
    for line in (
        "      Voice           Off\n",
        "      STT             Off\n      TTS             Off\n",
        "      Vectors         Qdrant · your server, from QDRANT_URL\n",
        "      Tools           None enabled (default)\n",
        "                      then run: alphaavatar setup vectors\n",
    ):
        assert line in out, line
    assert "WARN" not in out
    assert person.asked("for speech") == [] and person.asked("Voice ID") == []
    assert "Enter keeps" not in person.asked("QDRANT_URL")[0]
    memory = (profiles / "vectors/plugins/perception/memory.yaml").read_text()
    assert "  url: ${oc.env:QDRANT_URL}  # Your Qdrant server.\n" in memory
    assert not [p for p in profiles.rglob("*.yaml") if url in p.read_text()]  # Read, not written.
    voice = yaml.safe_load((profiles / "vectors/plugins/foundation/voice.yaml").read_text())
    assert [voice[part]["plugin"] for part in ("vad", "stt", "tts")] == [None, None, None]
    # Held by the .env file start reads, it is set: Enter keeps it.
    dotenv = Path("qdrant.env")
    dotenv.write_text(f"QDRANT_URL={url}\n")
    with mock.patch.dict(os.environ, {"ENV_FILE": str(dotenv.resolve())}):
        person = setup("from-file")
    assert "(set; Enter keeps it)" in person.asked("QDRANT_URL")[0]
    capsys.readouterr()


def test_a_name_a_bundle_has_is_asked_again_and_refused_as_given(
    package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    from alphaavatar.host.configs import application_paths
    from alphaavatar.host.configs.template import create_bundle

    create_bundle(application_paths(), "taken", avatar_id="taken")
    before = home_files()
    person = Person(
        ("Bundle name", "taken"), ("Bundle name", "fresh"), ("Install and enable?", "n")
    )
    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch("sys.stdin.isatty", return_value=True),
        mock.patch.dict(os.environ, CREDENTIALS),
        person.answering(),
    ):
        assert main(["setup"]) == 1  # Declined at the end: nothing written.
        assert "Bundle 'taken' exists" in capsys.readouterr().out
        assert person.rules == [] and len(person.asked("Bundle name")) == 2
        assert person.asked("Avatar ID [fresh]: ") != []
        # Given, the name is refused at once, before any other question.
        given = Person()
        with given.answering():
            assert main(["setup", "--name", "taken"]) != 0
        assert "Bundle 'taken' exists" in capsys.readouterr().err
        assert given.asked("Provider for") == []
    assert home_files() == before


def test_a_name_whose_profiles_exist_is_never_written_over_even_shared(
    package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    """Profiles named as a new bundle would name its own, there already and shared by another
    bundle: the name is asked again, or refused as given, before any question about it."""
    from alphaavatar.host.configs import application_paths
    from alphaavatar.host.configs.template import create_bundle

    paths = application_paths()
    create_bundle(paths, "keeper", avatar_id="keeper")
    configs = paths.configs.root
    # The keeper's memory profile moved under "orphan" and named there by its bundle.
    shared = configs / "profiles/orphan/plugins/perception/memory.yaml"
    shared.parent.mkdir(parents=True)
    (configs / "profiles/keeper/plugins/perception/memory.yaml").rename(shared)
    bundle = configs / "bundles/keeper.yaml"
    text = bundle.read_text()
    bundle.write_text(text.replace("memory: keeper/plugins/", "memory: orphan/plugins/"))
    before = {p: p.read_bytes() for p in configs.rglob("*") if p.is_file()}

    person = Person(
        ("Bundle name", "orphan"), ("Bundle name", "fresh"), ("Install and enable?", "n")
    )
    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch("sys.stdin.isatty", return_value=True),
        mock.patch.dict(os.environ, CREDENTIALS),
        person.answering(),
    ):
        assert main(["setup"]) == 1
        assert f"Profiles named 'orphan' exist: {shared.parents[2]}" in capsys.readouterr().out
        assert person.rules == [] and len(person.asked("Bundle name")) == 2
        given = Person()
        with given.answering():
            assert main(["setup", "--name", "orphan"]) != 0
        assert "Profiles named 'orphan' exist" in capsys.readouterr().err
        assert given.prompts[-1:] != [] and given.asked("Provider for") == []
    assert {p: p.read_bytes() for p in configs.rglob("*") if p.is_file()} == before


def test_an_existing_bundle_set_up_again_keeps_every_file_as_a_person_left_it(
    package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    """A bundle edited by hand, one of its profiles shared with another bundle, the default and
    the stored credentials another bundle reads: set up again, it is installed for as it is,
    asked nothing but whether to install; cancelled, failed or enabled, every file of the
    configuration stays to the byte, and so do the stored credentials."""
    from alphaavatar.host.configs import application_paths, load_application, select_configuration
    from alphaavatar.host.configs.credentials import credentials_path
    from alphaavatar.host.configs.template import create_bundle

    paths = application_paths()
    create_bundle(
        paths,
        "other",
        avatar_id="other",
        make_default=True,
        credentials={"OPENAI_API_KEY": "sk-stored-for-other"},
    )
    create_bundle(paths, "mine", avatar_id="mine")
    configs = paths.configs.root
    # Edited in place, comments and layout of a person's own; memory is the other bundle's.
    edits = {
        "profiles/mine/plugins/foundation/loop.yaml": (
            "    model: gpt-5.6-luna",
            "    model: gpt-4.1  # mine",
        ),
        "profiles/mine/plugins/foundation/voice.yaml": (
            "  speed: 1.15",
            "  speed: 1.3\n\n  # Slower, for me.",
        ),
        "profiles/other/plugins/perception/memory.yaml": (
            "  environment:\n    enabled: true",
            "  environment:\n    enabled: false  # Not mine.",
        ),
        "bundles/mine.yaml": ("memory: mine/plugins/", "memory: other/plugins/"),
    }
    for relative, (old, new) in edits.items():
        path = configs / relative
        assert path.read_text().count(old) == 1, relative
        path.write_text(path.read_text().replace(old, new))
    files = {p: p.read_bytes() for p in configs.rglob("*") if p.is_file()}
    stored = credentials_path(paths).read_bytes()
    settings = paths.settings_file.read_bytes()

    def failed(*args, check, enable, **kwargs):
        raise environment.SetupError("the environment fails its check")

    def installed(installation, plan, sources, *, check, enable, **kwargs):
        enable()
        return installation.environment(plan)

    def setup(install, answer: str | None) -> int:
        person = Person(*((("Install and enable?", answer),) if answer else ()))
        with (
            mock.patch.object(environment.Installation, "running", return_value=package),
            mock.patch.object(environment, "install", install),
            mock.patch("sys.stdin.isatty", return_value=True),
            mock.patch.dict(os.environ, CREDENTIALS),
            person.answering(),
        ):
            code = main(["setup", "mine"])
        # No questionnaire: only whether to install what the bundle's settings need.
        assert [p.strip() for p in person.prompts] == ["Install and enable? [Y/n]:"]
        return code

    assert setup(installed, "n") == 1  # Cancelled.
    assert "ENV memory off" in capsys.readouterr().out  # Planned from its settings as edited.
    assert setup(failed, "y") == 1  # Failed.
    assert {p: p.read_bytes() for p in configs.rglob("*") if p.is_file()} == files
    assert (paths.settings_file.read_bytes(), credentials_path(paths).read_bytes()) == (
        settings,
        stored,
    )
    assert setup(installed, "y") == 0  # Enabled.
    assert {p: p.read_bytes() for p in configs.rglob("*") if p.is_file()} == files
    assert credentials_path(paths).read_bytes() == stored  # Another bundle's, untouched.
    # Enabled: the default now, everything else as it was; it runs with the edits.
    assert yaml.safe_load(paths.settings_file.read_text())["default_bundle"] == "mine"
    avatar = load_application(select_configuration("mine")).avatar
    assert avatar.loop.init_config["model"]["model"] == "gpt-4.1"
    assert avatar.voice.tts.speed == 1.3
    assert avatar.memory.init_config["environment"]["enabled"] is False
    capsys.readouterr()


def _recorded_default(paths, *, named: bool) -> tuple[Path, dict]:
    """The bundle mine, its Avatar's memory table recorded for OpenAI's embedding at the default
    directory, as the version before wrote it, with the settings naming that directory as
    client_path or (``named`` false) naming none; the bundle now naming Google's, and no
    directory."""
    from alphaavatar.host.configs.template import create_bundle

    create_bundle(paths, "mine", avatar_id="mine")
    default = paths.workspace("mine").data.indexes.namespace("memory").backend("lancedb").root
    default.mkdir(parents=True)
    record = {
        "alphaavatar.embedding_space": 1,
        "provider": "openai",
        "model": "text-embedding-3-small",
        "dimensions": None,
        "size": 1536,
        "store": "memory",
        "setting": "memory.vdb_config.collection_name",
        "client_path": str(default) if named else None,
    }
    (default / "memory.embedding.json").write_text(json.dumps(record))
    memory = paths.configs.root / "profiles/mine/plugins/perception/memory.yaml"
    google = "    provider: google\n    model: text-embedding-004"
    memory.write_text(
        memory.read_text().replace(
            "    provider: openai\n    model: text-embedding-3-small", google
        )
    )
    return default, record


def _set_up(package: environment.Installation) -> tuple[int, mock.Mock]:
    def installed(installation, plan, sources, *, check, enable, **kwargs):
        enable()
        return installation.environment(plan)

    install = mock.Mock(side_effect=installed)
    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch.object(environment, "install", install),
        mock.patch("sys.stdin.isatty", return_value=False),
        mock.patch.dict(os.environ, CREDENTIALS),
    ):
        return main(["setup", "mine"]), install


def test_setup_reads_the_record_where_start_opens_the_store(
    package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    """The settings no longer name the directory: the runner opens the table there still, so
    its record counts, however it was named when made."""
    from alphaavatar.host.configs import application_paths

    paths = application_paths()
    default, record = _recorded_default(paths, named=True)
    kept = {p: p.read_bytes() for p in paths.root.rglob("*") if p.is_file()}
    code, install = _set_up(package)
    assert code == 1 and not install.called
    assert f"LanceDB table 'memory' in {default} holds vectors of openai" in capsys.readouterr().err
    assert {p: p.read_bytes() for p in paths.root.rglob("*") if p.is_file()} == kept


def test_setup_leaves_a_store_moved_aside_to_itself(package: environment.Installation) -> None:
    """Moved aside by hand: the default directory holds no store, and gets a new one; the one
    moved aside is no store the settings open, and stays as it is."""
    from alphaavatar.host.configs import application_paths

    paths = application_paths()
    default, record = _recorded_default(paths, named=False)
    backup = default.with_name("lancedb-backup")
    default.rename(backup)
    code, install = _set_up(package)
    assert code == 0 and install.called
    assert json.loads((backup / "memory.embedding.json").read_text()) == record


def test_a_bundle_naming_another_embedding_for_the_vectors_its_avatar_keeps_is_refused_first(
    package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    """The Avatar's memory vectors made with one embedding, its bundle now naming another for
    the same store: setup refuses before anything is installed or asked, and keeps everything;
    a separate index, another collection name, installs. A new bundle for that Avatar too."""
    from alphaavatar.agents.utils.vdb.space import EmbeddingSpace
    from alphaavatar.host.configs import application_paths
    from alphaavatar.host.configs.template import create_bundle

    paths = application_paths()
    create_bundle(paths, "mine", avatar_id="mine")
    store = paths.workspace("mine").data.indexes.namespace("memory").backend("lancedb").root
    store.mkdir(parents=True)
    small = {"provider": "openai", "model": "text-embedding-3-small"}
    record = EmbeddingSpace.configured(small, 1536).record(
        store="memory", setting="memory.vdb_config.collection_name"
    )
    (store / "memory.embedding.json").write_text(json.dumps(record))
    memory = paths.configs.root / "profiles/mine/plugins/perception/memory.yaml"
    text = memory.read_text()
    google = "    provider: google\n    model: text-embedding-004"
    memory.write_text(
        text.replace("    provider: openai\n    model: text-embedding-3-small", google)
    )
    kept = {p: p.read_bytes() for p in paths.root.rglob("*") if p.is_file()}

    def installed(installation, plan, sources, *, check, enable, **kwargs):
        enable()
        return installation.environment(plan)

    install = mock.Mock(side_effect=installed)
    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch.object(environment, "install", install),
        mock.patch("sys.stdin.isatty", return_value=False),
        mock.patch.dict(os.environ, CREDENTIALS),
    ):
        assert main(["setup", "mine"]) == 1
        said = capsys.readouterr().err
        assert (
            f"LanceDB table 'memory' in {store} holds vectors of openai text-embedding-3-small"
            in said
        )
        assert "give memory.vdb_config.collection_name another name, a separate index" in said
        assert not install.called
        assert {p: p.read_bytes() for p in paths.root.rglob("*") if p.is_file()} == kept
        # A separate index: installed, the first index and its record as they were.
        memory.write_text(
            memory.read_text().replace("collection_name: memory", "collection_name: memory_google")
        )
        assert main(["setup", "mine"]) == 0
        # The same name in a Qdrant server: another store, not the workspace's table.
        qdrant = memory.read_text().replace(
            "collection_name: memory_google", "collection_name: memory"
        )
        memory.write_text(qdrant.replace("  url: null", "  url: ${oc.env:QDRANT_URL}"))
        with mock.patch.dict(os.environ, {"QDRANT_URL": "https://vectors.invalid:6333"}):
            assert main(["setup", "mine"]) == 0
    assert json.loads((store / "memory.embedding.json").read_text()) == record

    # A new bundle for the same Avatar, its embeddings from Google: refused before credentials.
    person = Person(
        ("Bundle name", "again"),
        ("Avatar ID", "mine"),
        ("Provider for embeddings", "google"),
        ("Model for embeddings", "text-embedding-004"),
    )
    install.reset_mock()
    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch.object(environment, "install", install),
        mock.patch("sys.stdin.isatty", return_value=True),
        mock.patch.dict(os.environ, CREDENTIALS),
        person.answering(),
    ):
        assert main(["setup"]) == 1
    assert "holds vectors of openai text-embedding-3-small" in capsys.readouterr().err
    assert person.rules == [] and person.asked("API_KEY") == [] and not install.called
    assert not (paths.configs.root / "bundles/again.yaml").exists()


def test_a_build_that_is_no_release_needs_its_wheels_named_before_anything_is_asked(
    package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    """A CI or local build publishes its own wheels nowhere: without --artifacts, a new bundle
    is refused before its first question, and an existing one before installing; given, or
    with nothing to download, setup goes on. The plan alone needs no wheel."""
    manifest = package.base / "share/alphaavatar/manifest.json"
    manifest.write_text(json.dumps({"id": "base-1", "release": None}))
    install = mock.Mock(
        side_effect=lambda installation, plan, *a, enable, **k: (
            enable(),
            installation.environment(plan),
        )[1]
    )
    said = "AlphaAvatar base-1 is not a release, so its own wheels are published nowhere"
    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch.object(environment, "install", install),
        mock.patch.dict(os.environ, CREDENTIALS),
    ):
        asked = Person()
        with mock.patch("sys.stdin.isatty", return_value=True), asked.answering():
            assert main(["setup"]) == 1
        assert said in capsys.readouterr().err and asked.prompts == [] and not install.called
        assert main(["config", "init", "mine", "--avatar-id", "mine"]) == 0
        capsys.readouterr()
        with mock.patch("sys.stdin.isatty", return_value=False):
            assert main(["setup", "mine"]) == 1
            assert "`alphaavatar setup --artifacts DIR`" in capsys.readouterr().err
            assert main(["setup", "mine", "--plan"]) == 0
            assert main(["setup", "mine", "--artifacts", "/srv/build"]) == 0
            assert install.call_args.args[2] == environment.Sources("/srv/build", None)
    assert home_files()  # Enabled: given its wheels, nothing else was needed.
