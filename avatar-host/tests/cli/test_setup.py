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

import json
import logging
import os
import re
import signal
import stat
import sys
from pathlib import Path
from unittest import mock

import pytest
import yaml

# Imported at collection: the persona plugin's OpenCV adjusts process variables (O-2).
import alphaavatar.plugins.persona.factory  # noqa: F401
from alphaavatar.host.cli.app import main
from alphaavatar.host.setup import environment
from alphaavatar.host.setup.choices import Selection, requirements, sections

CREDENTIALS = {
    "OPENAI_API_KEY": "sk-fictional-0042",
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


@pytest.fixture
def package(tmp_path: Path) -> environment.Installation:
    """An installed base whose catalog holds what the reference configuration needs."""
    base = tmp_path / "prefix" / "versions" / "base-1"
    (base / "share" / "alphaavatar").mkdir(parents=True)
    names = [text.split("[")[0] for text in requirements(Selection())]
    keys = {text: [text.split("[")[0]] for text in requirements(Selection())}
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
    (base / "share/alphaavatar/manifest.json").write_text(json.dumps({"id": "base-1"}))
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
        assert "Bundle 'reference' does not exist" in capsys.readouterr().err
        assert main(["config", "init", "reference", "--avatar-id", "reference"]) == 0
        capsys.readouterr()
        # The plan alone changes nothing, and is the same plan each time.
        assert main(["setup", "reference", "--plan"]) == 0
        first = capsys.readouterr()
        assert main(["setup", "reference", "--plan"]) == 0
        assert json.loads(capsys.readouterr().out) == json.loads(first.out)
        assert json.loads(first.out)["requirements"] == list(requirements(Selection()))
        steps = "01  Capabilities   Bundle reference · Voice on · Vision on · Local models on\n"
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


def test_typed_session_credentials_are_checked_before_anything_is_stored_or_installed(
    package: environment.Installation,
    capsys: pytest.CaptureFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The key and secret typed as the URL, as a host and a port: the values that take
    # effect, typed over what the environment holds, are the ones checked.
    typed = ("sk-new", "wss://lk-key:lk-fictional-secret", "lk-key", "lk-fictional-secret")
    asked, hidden = answers("", "", "", "", "", "", "second", "", *typed)
    caplog.set_level(logging.DEBUG)
    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch.object(environment, "install") as install,
        mock.patch("sys.stdin.isatty", return_value=True),
        mock.patch.dict(os.environ, CREDENTIALS),
        asked,
        hidden,
    ):
        assert main(["setup"]) == 1
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
    before = home_files()
    home = Path.home() / ".local/share/alphaavatar"

    def default() -> str:
        return yaml.safe_load((home / "settings/settings.yaml").read_text())["default_bundle"]

    def failed(*args, check, enable, **kwargs):
        raise environment.SetupError("the environment fails its check")

    def installed(installation, plan, sources, *, check, enable, **kwargs):
        assert sources == environment.Sources("/ci/run", None)
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
    # The environment's credentials stay there: nothing stores them.
    assert "credentials" not in yaml.safe_load((home / "settings/settings.yaml").read_text())
    assert not [path.name for path in (home / "settings").iterdir() if "credentials" in path.name]
    shown = capsys.readouterr().out.splitlines()
    assert "02  Credentials    From the environment, .env or those stored" in shown
    assert shown[-4:] == ["", "Next", "  alphaavatar doctor reference", ""]


def answers(*lines: str):
    """input() and getpass() answering in order, as a person at the terminal would."""
    queue = list(lines)
    return mock.patch("builtins.input", lambda prompt="": queue.pop(0)), mock.patch(
        "getpass.getpass", lambda prompt="": queue.pop(0)
    )


def test_the_plan_alone_goes_to_stdout_even_when_setup_asks(
    package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    # Voice, vision, no local models, LanceDB, OpenAI's models and speech; the name, its ID.
    queue = ["", "", "n", "", "", "", "remote", ""]

    def typed(prompt: str = "") -> str:
        sys.stdout.write(prompt)  # As input() shows its prompt.
        return queue.pop(0)

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
    assert "From the reference configuration" in output.err
    # (Answered here without a terminal's echo, so a prompt and the next line share one.)
    assert "01  Capabilities   Voice on · Vision on · Local models off\n" in output.err
    assert home_files() == []


def test_a_plan_declined_installs_and_enables_nothing(
    package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    installed = mock.Mock(side_effect=AssertionError("nothing installs"))
    # No local models, its name and ID, the credentials set already, not stored; then no.
    asked, hidden = answers("", "", "n", "", "", "", "remote", "", "", "", "", "", "n", "n")
    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch.object(environment, "install", installed),
        mock.patch("sys.stdin.isatty", return_value=True),
        mock.patch.dict(os.environ, CREDENTIALS),
        asked,
        hidden,
    ):
        assert main(["setup"]) == 1
    output = capsys.readouterr()
    # The plan and what it downloads were shown before the question; then nothing changed.
    assert re.search(r"\n    \d+ packages · 0 MB to download\n", output.out)
    assert output.err == "WARN  Cancelled; nothing was enabled\n\n"
    assert home_files() == []


def test_ctrl_c_at_a_question_enables_nothing_and_says_so(
    package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    def answer(prompt: str = "") -> str:
        sys.stdout.write(prompt)  # As input() shows its prompt.
        if "Bundle name" in prompt:
            raise KeyboardInterrupt
        return ""  # Each part as the reference has it.

    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch("sys.stdin.isatty", return_value=True),
        mock.patch("builtins.input", answer),
    ):
        assert main(["setup"]) == 130
    output = capsys.readouterr()
    assert output.err == "WARN  Interrupted; nothing was enabled\n\n"
    # The question's line ends, then a blank line: the outcome stands apart from the steps.
    assert output.out.endswith("    Bundle name [avatar]: \n\n")
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

    typed = ("sk-new", "wss://livekit.invalid", "lk-key", "lk-secret")
    asked, hidden = answers("", "", "", "", "", "", "second", "", *typed, "y", "n", "y")
    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch.object(environment, "install", installed),
        mock.patch("sys.stdin.isatty", return_value=True),
        mock.patch.dict(os.environ),
        asked,
        hidden,
    ):
        assert main(["setup"]) == 0
    output = capsys.readouterr().out
    stored = credentials_path(paths).read_text()
    # The earlier bundle's key stays; what was new is stored, readable only by the person.
    assert 'OPENAI_API_KEY="sk-earlier"' in stored and "sk-new" not in stored
    assert 'LIVEKIT_API_SECRET="lk-secret"' in stored
    assert stat.S_IMODE(credentials_path(paths).stat().st_mode) == 0o600
    assert "OPENAI_API_KEY stays as stored" in output and "sk-new" not in output


def test_a_key_stored_for_one_server_of_ones_own_serves_no_other(
    package: environment.Installation, capsys: pytest.CaptureFixture
) -> None:
    from alphaavatar.host.configs import application_paths, load_application, select_configuration
    from alphaavatar.host.configs.credentials import stored_credentials
    from alphaavatar.host.setup.choices import server_key

    a, b = "http://a.invalid:8000/v1", "http://b.invalid:8000/v1"
    prompts: list[str] = []

    def installed(installation, plan, sources, *, check, enable, **kwargs):
        enable()
        return installation.environment(plan)

    def setup(name: str, server: str, *typed: str) -> int:
        # No voice, vision, no local models, LanceDB, the models from `server`; then the
        # name, the Avatar ID, the server's key, LiveKit's (set: Enter keeps them).
        queue = ["n", "y", "n", "1", "n", server, "chat", "", "embed", name, "", *typed]

        def answer(prompt: str = "") -> str:
            prompts.append(prompt)
            return queue.pop(0)

        livekit = {
            "LIVEKIT_URL": "wss://lk.invalid",
            "LIVEKIT_API_KEY": "k",
            "LIVEKIT_API_SECRET": "s",
        }
        with (
            mock.patch.object(environment.Installation, "running", return_value=package),
            mock.patch.object(environment, "install", installed),
            mock.patch("sys.stdin.isatty", return_value=True),
            # Wide: each question is one prompt, as this test reads them.
            mock.patch.dict(os.environ, livekit | {"COLUMNS": "200"}),
            mock.patch("builtins.input", answer),
            mock.patch("getpass.getpass", answer),
        ):
            return main(["setup"])

    def asked(server: str) -> str:
        return next(p for p in reversed(prompts) if p.strip().startswith(server_key(server)))

    paths = application_paths()
    assert setup("first", a, "key-a", "", "", "", "y", "y") == 0
    # Another server's key is not this one's: Enter keeps nothing, and the key is missing.
    assert setup("second", b, "", "", "", "") == 1
    assert "Enter keeps" not in asked(b)
    assert f"Missing credentials: {server_key(b)}" in capsys.readouterr().err
    assert stored_credentials(paths)[server_key(a)] == "key-a"
    # Storing the other server's key leaves the first server's, which the first bundle reads.
    assert setup("third", b, "key-b", "", "", "", "y", "y") == 0
    stored = stored_credentials(paths)
    assert (stored[server_key(a)], stored[server_key(b)]) == ("key-a", "key-b")
    first = load_application(select_configuration("first")).avatar.loop.init_config["model"]
    assert first["extra"] == {"base_url": a, "api_key_env": server_key(a)}
    # The same server again: its stored key serves it, kept with Enter.
    assert setup("fourth", a, "", "", "", "", "y") == 0
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

    typed = ("sk-new", "wss://livekit.invalid", "lk-key", "lk-secret")
    asked, hidden = answers("", "", "", "", "", "", "second", "", *typed, "y", "y")
    with (
        mock.patch.object(environment.Installation, "running", return_value=package),
        mock.patch.object(environment, "check_environment", lambda *args: None),
        mock.patch.object(os, "replace", replacing),
        mock.patch.object(stored, "write_credentials", writing),
        mock.patch("sys.stdin.isatty", return_value=True),
        mock.patch.dict(os.environ),
        asked,
        hidden,
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
