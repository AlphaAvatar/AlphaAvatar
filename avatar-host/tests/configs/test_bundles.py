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
"""Bundles, profiles and the default bundle: selection, creation and failure boundaries."""

from __future__ import annotations

import errno
import io
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from unittest import mock

import pytest
import yaml
from config_samples import CONFIG, LAYOUT, LOOP, SECRETS, SECTIONS, files, write

# Imported at collection: the persona plugin's OpenCV adjusts process variables (O-2).
import alphaavatar.plugins.persona  # noqa: F401
from alphaavatar.agents.runtime.inference import plan_inference_runners
from alphaavatar.host.cli.app import main
from alphaavatar.host.configs import (
    application_paths,
    create_bundle,
    load_application,
    select_configuration,
    template,
    validate_plugin_settings,
)
from alphaavatar.host.configs.bundles import LAYERS, profile_sections
from alphaavatar.host.configs.loader import restore_application
from alphaavatar.plugins.context.config import ContextConfig
from alphaavatar.plugins.memory.config import DefaultMemoryConfig
from alphaavatar.plugins.persona.config import DefaultPersonaConfig
from alphaavatar.plugins.persona.processors.face.analysis_runner import FaceAnalysisRunner
from alphaavatar.plugins.router.config import RouterConfig

# The single-file template `config init` wrote before bundles, its YAML anchors included.
SINGLE_FILE_TEMPLATE = """\
avatar: {id: my-avatar, name: Assistant, introduction: You are a helpful voice AI assistant.}
defaults:
  embedding: &embedding {provider: openai, model: text-embedding-3-small}
  task: &task {provider: openai, model: gpt-4o, temperature: 0.1}
loop:
  plugin: realtime
  init_config: {model: {backend: openai, provider: openai, model: gpt-5.6-luna}}
voice:
  vad: {plugin: silero}
  stt: {plugin: openai_segment, model: gpt-4o-transcribe}
  tts: {plugin: openai, model: gpt-4o-mini-tts, speaker: ash}
vision: {enabled: false}
memory:
  vdb_config: {collection_name: memory, embedding: *embedding}
  init_config:
    conversation: {provider: {gateway: {tasks: {memory.conversation_delta: *task}}}}
    tool: {provider: {gateway: {tasks: {memory.tool_delta: *task}}}}
persona:
  vdb_config:
    profiler_collection_name: persona_profiler
    speaker_collection_name: persona_speaker
    face_collection_name: persona_face
    embedding: *embedding
  init_config:
    profiler: {provider: {gateway: {tasks: {persona.profile_delta: *task}}}}
tools: {deepresearch: {plugin: null}, rag: {plugin: null}, mcp: {enabled: false}}
"""
# The Context profile body `config init` wrote while the history had capacity limits.
LEGACY_CONTEXT = """\
plugin: default
init_config:
  history_max_turns: 32
  history_max_items: 4096
  history_max_bytes: 8388608
"""


# The default bundle's runner plan, from an interpreter that has imported no plugin yet, then
# accepted again with every planned runner's workers overridden.
PLAN_PROBE = """
import json, sys
from alphaavatar.agents.runtime.inference import plan_inference_runners
from alphaavatar.host.configs import load_application, select_configuration
imported = sorted(name for name in sys.modules if name.startswith("alphaavatar.plugins"))
source = select_configuration(None)
config = load_application(source)
runners = plan_inference_runners(config.avatar)
workers = {method: 2 if runner.REPLICABLE else 1 for method, runner in runners.items()}
methods = {method: {"workers": count} for method, count in workers.items()}
tuned = load_application(source, [f"runtime.inference.methods={json.dumps(methods)}"])
print(json.dumps({
    "imported": imported,
    "vision": config.avatar.vision.enabled,
    "planned": list(runners),
    "workers": {method: tuned.avatar.runtime.inference.workers(method) for method in workers},
}))
"""
HANG_GUARD = 30
VOICE = f"alpha/{LAYOUT['voice']}"


LOCK = "application/settings/.write.lock"


def contents(root: Path) -> dict[str, bytes | None]:
    """Every path under root with its bytes; None marks a directory."""
    return {
        str(path.relative_to(root)): None if path.is_dir() else path.read_bytes()
        for path in root.rglob("*")
    }


def create(name: str, avatar_id: str) -> int:
    return main(["config", "init", name, "--avatar-id", avatar_id])


def profile(home: Path, name: str) -> Path:
    return home / "configs" / "profiles" / f"{name}.yaml"


def speaker(loaded: object) -> str:
    return json.loads(loaded.payload)["voice"]["tts"]["speaker"]


def test_init_splits_the_minimal_template_into_a_bundle_and_profiles_that_load_unchanged(
    tmp_path: Path,
    home: Path,
    sandbox: list[str],
    credentials: object,
    capsys: pytest.CaptureFixture,
) -> None:
    before = files(tmp_path)
    assert create("my-avatar", "my-avatar") == 0
    output = capsys.readouterr().out
    bundle = home / "configs" / "bundles" / "my-avatar.yaml"
    profiles = [profile(home, f"my-avatar/{LAYOUT[section]}") for section in SECTIONS]
    settings = home / "settings" / "settings.yaml"
    # Configuration files and their directories only: no cache, workspace or log.
    lock = settings.with_name(".write.lock")  # Kept by the lock library, as elsewhere.
    created = {
        str(path.relative_to(tmp_path))
        for target in (bundle, settings, lock, *profiles)
        for path in (target, *target.parents)
        if path.is_relative_to(home)
    }
    assert sorted(set(files(tmp_path)) - set(before)) == sorted(created)
    # Locations and the default choice, never the configuration itself.
    assert f"  bundle    {bundle}\n" in output
    layers = "host, agent, plugins/foundation, plugins/perception, plugins/tools"
    assert f"  profiles  {home / 'configs' / 'profiles' / 'my-avatar'}  ({layers})\n" in output
    # Every section a profile may fill has a layer, so init and check cover them all.
    assert set(LAYERS) == profile_sections() == set(SECTIONS)
    assert "  default   my-avatar (set as the default bundle)\n" in output
    assert "OPENAI_API_KEY" in output and "alphaavatar dev my-avatar" in output
    assert "gpt-4o" not in output and "silero" not in output

    for path in (bundle, *profiles):
        text = path.read_text()
        # Each file stands alone: no YAML anchor or alias reaches across files.
        events = list(yaml.parse(text))
        assert not any(isinstance(event, yaml.AliasEvent) for event in events)
        assert not any(getattr(event, "anchor", None) for event in events)
        assert str(tmp_path) not in text
        assert [name for name, secret in SECRETS.items() if secret in text] == []
    assert yaml.safe_load(bundle.read_text()) == {
        "avatar": {
            "id": "my-avatar",
            "name": "Assistant",
            "introduction": "You are a helpful voice AI assistant.",
        },
        "profiles": {section: f"my-avatar/{LAYOUT[section]}" for section in SECTIONS},
    }
    assert yaml.safe_load(settings.read_text()) == {"default_bundle": "my-avatar"}

    # The composed configuration is the previous single-file template as the plugins read it:
    # the added profiles spell out defaults that the single file left implicit.
    def effective(loaded: object) -> dict:
        payload = json.loads(loaded.payload)
        for section, schema in (
            ("context", ContextConfig),
            ("router", RouterConfig),
            ("memory", DefaultMemoryConfig),
            ("persona", DefaultPersonaConfig),
        ):
            options = schema.model_validate(payload[section]["init_config"])
            payload[section]["init_config"] = options.model_dump(mode="json")
        return payload

    single = tmp_path / "single.yaml"
    single.write_text(SINGLE_FILE_TEMPLATE)
    # The reference bundle sees: vision is on, where the single file left it off.
    expected = effective(load_application(single, ["vision.enabled=true"]))
    for target in (None, "my-avatar", str(bundle)):
        loaded = load_application(select_configuration(target))
        assert effective(loaded) == expected
    assert main(["config", "check", "--json"]) == 0
    plugins = json.loads(capsys.readouterr().out)["plugins"]
    assert plugins["voice"] == {"vad": "silero", "stt": "openai_segment", "tts": "openai"}
    assert plugins["vision"] == {"enabled": True, "input": "vlm"}
    assert (plugins["memory"]["vdb"], plugins["persona"]["vdb"]) == ("lancedb", "lancedb")
    assert plugins["tools"] == {"deepresearch": None, "rag": None, "mcp": None}
    assert sandbox == []


def test_the_reference_bundle_sees_and_plans_its_runners_in_a_fresh_interpreter(
    home: Path, credentials: object, capsys: pytest.CaptureFixture
) -> None:
    assert create("reference", "reference") == 0
    probe = subprocess.run(
        [sys.executable, "-c", PLAN_PROBE],
        capture_output=True,
        text=True,
        timeout=120,
        env=os.environ,
    )
    assert probe.returncode == 0, probe.stderr
    found = json.loads(probe.stdout.splitlines()[-1])
    # Nothing registered on import: planning imported the selected plugins itself and found
    # the runners this process, with every plugin imported, plans for the same bundle.
    assert found["imported"] == []
    expected = plan_inference_runners(load_application(select_configuration(None)).avatar)
    assert found["planned"] == list(expected)
    assert found["vision"] and FaceAnalysisRunner.INFERENCE_METHOD in found["planned"]
    # Worker overrides name selected runners only; replicable ones take several.
    assert found["workers"] == {
        method: 2 if runner.REPLICABLE else 1 for method, runner in expected.items()
    }
    assert any(count == 2 for count in found["workers"].values())


def test_selection_follows_the_argument_spelling_from_any_directory(
    tmp_path: Path,
    home: Path,
    sandbox: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    assert create("alpha", "alpha") == 0 and create("beta", "beta-avatar") == 0
    capsys.readouterr()
    bundles = home / "configs" / "bundles"
    # Files in the working directory named like bundles are read only when spelled as files.
    for name in ("beta", "missing"):
        write(tmp_path / f"{name}.yaml", {"avatar": {"id": f"{name}-file"}, "loop": LOOP})
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    before = files(tmp_path)

    def checked(*argv: str) -> tuple[dict, str]:
        assert main(["config", "check", *argv, "--json"]) == 0
        report = json.loads(capsys.readouterr().out)
        return report["config"], report["avatar_id"]

    def named(name: str, default: bool = False) -> dict:
        return {"bundle": name, "default": default, "file": str(bundles / f"{name}.yaml")}

    for directory in (tmp_path, elsewhere):
        monkeypatch.chdir(directory)
        assert checked() == (named("alpha", default=True), "alpha")
        assert checked("beta") == (named("beta"), "beta-avatar")
        # KEY=VALUE is always an override; alone, it overrides the default bundle.
        assert checked("avatar.id=renamed") == (named("alpha", default=True), "renamed")
        assert checked("beta", "avatar.id=renamed") == (named("beta"), "renamed")
        assert checked(str(bundles / "beta.yaml"))[1] == "beta-avatar"
    monkeypatch.chdir(tmp_path)
    local = {"bundle": None, "default": False, "file": str(tmp_path / "beta.yaml")}
    assert checked("beta.yaml") == checked("./beta.yaml") == (local, "beta-file")
    # A missing bundle never falls back to a file; a name outside the alphabet is no path.
    for argument, message in (
        ("missing", f"Bundle 'missing' does not exist: {bundles / 'missing.yaml'}"),
        ("Beta", "Bundle names use 1-64 lowercase letters"),
    ):
        assert main(["config", "check", argument]) == 2
        assert message in capsys.readouterr().err
    assert (files(tmp_path), sandbox) == (before, [])

    # Overrides apply to the composed configuration; profiles.<section> picks a reference.
    beta = f"beta/{LAYOUT['voice']}"
    voice = profile(home, beta)
    voice.write_text(voice.read_text().replace("speaker: ash", "speaker: shimmer"))
    for overrides, expected in (
        ((), "ash"),
        (("voice.tts.speaker=nova",), "nova"),
        ((f"profiles.voice={beta}",), "shimmer"),
        ((f"profiles.voice={beta}", "voice.tts.speaker=nova"), "nova"),
    ):
        source = select_configuration("alpha", overrides)
        assert speaker(load_application(source, overrides)) == expected


def test_without_a_default_bundle_selection_fails_clearly_and_settings_never_choose_the_home(
    tmp_path: Path, home: Path, capsys: pytest.CaptureFixture
) -> None:
    settings = home / "settings" / "settings.yaml"
    other = tmp_path / "other"
    for text in (None, "default_bundle: null\n", f"theme: dark\napplication: {{home: {other}}}\n"):
        if text is not None:
            settings.parent.mkdir(parents=True, exist_ok=True)
            settings.write_text(text)
        before = contents(tmp_path)
        assert main(["config", "check"]) == 2
        error = capsys.readouterr().err
        assert f"no default bundle in {settings};" in error
        assert "alphaavatar config init <name> --avatar-id <id>" in error
        assert contents(tmp_path) == before

    # The first bundle becomes the default beside the other settings; the home stays put.
    assert create("alpha", "alpha") == 0
    capsys.readouterr()
    assert yaml.safe_load(settings.read_text()) == {
        "theme": "dark",
        "application": {"home": str(other)},
        "default_bundle": "alpha",
    }
    assert main(["config", "check", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["home"] == str(home)
    assert not other.exists()

    # A default naming a missing or malformed bundle fails without echoing the setting.
    for text, message in (
        ("default_bundle: gone\n", "Default bundle 'gone' does not exist"),
        (f"default_bundle: {SECRETS['vdb']}.Bad\n", f"default_bundle in {settings} is not"),
        ("- a list\n", "Settings must be a mapping"),
        (f"default_bundle: [{SECRETS['vdb']}\n", "Settings are not valid YAML"),
    ):
        settings.write_text(text)
        assert main(["config", "check"]) == 2
        error = capsys.readouterr().err
        assert message in error and SECRETS["vdb"] not in error


@pytest.mark.parametrize(
    ("bundle", "voice", "message"),
    [
        ({}, None, f"profiles.voice references missing profile '{VOICE}'"),
        ({"profiles": {"voice": "../alpha/voice"}}, "", "profiles.voice must be a profile name"),
        ({"profiles": {"voice": "/alpha/voice"}}, "", "profiles.voice must be a profile name"),
        ({"profiles": {"voice": "Alpha/Voice"}}, "", "profiles.voice must be a profile name"),
        ({"profiles": {"voice": "alpha/voice.yaml"}}, "", "profiles.voice must be a profile name"),
        ({"profiles": {"avatar": VOICE}}, "", "profiles may only fill character, context, host"),
        ({"profiles": VOICE}, "", "profiles must map sections to profile names"),
        ({"voice": {"vad": {"plugin": "silero"}}}, "", "voice is set both inline and by profiles"),
        ({}, f"profiles: {{voice: {VOICE}}}\n", f"'{VOICE}' references profiles; only bundles"),
        ({}, "- vad\n", f"profile '{VOICE}' must be a mapping"),
        ({}, f"tts: {{speaker: '{SECRETS['vdb']}\n", f"profile '{VOICE}' is not valid YAML"),
        ({"application": {"home": "/elsewhere"}}, "", "sets another application.home"),
    ],
    ids=[
        "missing",
        "parent",
        "absolute",
        "uppercase",
        "suffix",
        "not-a-section",
        "not-a-mapping",
        "inline-and-profile",
        "self-reference",
        "profile-list",
        "profile-yaml",
        "bundle-home",
    ],
)
def test_reference_errors_locate_the_bundle_and_profile_without_values(
    bundle: dict, voice: str | None, message: str, tmp_path: Path, home: Path, capsys
) -> None:
    assert create("alpha", "alpha") == 0
    capsys.readouterr()
    path, target = home / "configs" / "bundles" / "alpha.yaml", profile(home, VOICE)
    data = yaml.safe_load(path.read_text())
    for key, value in bundle.items():
        merge = isinstance(value, dict) and isinstance(data.get(key), dict)
        data[key] = data[key] | value if merge else value
    path.write_text(yaml.safe_dump(data))
    if voice is None:
        target.unlink()
    elif voice:
        target.write_text(voice)
    before = contents(tmp_path)

    assert main(["config", "check", "alpha"]) == 2
    error = capsys.readouterr().err
    assert main(["config", "check", "alpha", "--json"]) == 2
    report = json.loads(capsys.readouterr().out)["error"]
    assert "error: ConfigReferenceError\n    Bundle 'alpha'" in error and message in error
    assert report["type"] == "ConfigReferenceError" and message in report["diagnostic"]
    if voice is None:
        assert str(target) in error
    assert SECRETS["vdb"] not in error + json.dumps(report)
    assert contents(tmp_path) == before


def test_bundles_share_profiles_and_an_accepted_snapshot_stays_frozen(
    home: Path, capsys: pytest.CaptureFixture
) -> None:
    assert create("alpha", "alpha") == 0
    capsys.readouterr()
    # Generation groups profiles by bundle; any bundle may reference them.
    references = {section: f"alpha/{LAYOUT[section]}" for section in ("voice", "memory")}
    write(
        home / "configs" / "bundles" / "beta.yaml", {"avatar": {"id": "b"}, "profiles": references}
    )
    alpha, beta = (load_application(select_configuration(name)) for name in ("alpha", "beta"))
    for section in references:
        assert json.loads(beta.payload)[section] == json.loads(alpha.payload)[section]

    voice = profile(home, VOICE)
    voice.write_text(voice.read_text().replace("speaker: ash", "speaker: nova"))
    assert speaker(load_application(select_configuration("beta"))) == "nova"
    # Sessions restore the accepted payload; profiles on disk are never read again.
    shutil.rmtree(home / "configs" / "profiles")
    for accepted in (alpha, beta):
        restored = restore_application(accepted.payload)
        assert json.loads(restored.payload) == json.loads(accepted.payload)
        assert speaker(restored) == "ash"


def test_a_context_profile_with_the_removed_history_limits_still_loads(
    home: Path, capsys: pytest.CaptureFixture
) -> None:
    assert create("alpha", "alpha") == 0
    context = profile(home, f"alpha/{LAYOUT['context']}")
    header = context.read_text().partition("plugin: default")[0]
    context.write_text(header + LEGACY_CONTEXT)
    capsys.readouterr()
    # What start reads before it builds anything: the bundle, then each plugin's settings.
    assert main(["config", "check", "alpha", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True
    loaded = load_application(select_configuration("alpha"))
    assert validate_plugin_settings(loaded)["context"] == ContextConfig()
    # Their values are ignored; any other unknown setting is still refused, by its location.
    context.write_text(header + LEGACY_CONTEXT + "  history_max_tokens: 1\n")
    assert main(["config", "check", "alpha", "--json"]) == 2
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["fields"] == ["context.init_config.history_max_tokens"]


def test_checking_a_bundle_reads_only_and_hides_profile_credentials(
    tmp_path: Path,
    home: Path,
    sandbox: list[str],
    credentials: object,
    capsys: pytest.CaptureFixture,
) -> None:
    assert create("alpha", "alpha") == 0
    capsys.readouterr()
    for section, change in (("memory", CONFIG["memory"]), ("tools", CONFIG["tools"])):
        path = profile(home, f"alpha/{LAYOUT[section]}")
        data = yaml.safe_load(path.read_text())
        for key, value in change.items():
            data[key] = data.get(key, {}) | value
        path.write_text(yaml.safe_dump(data))
    before, environment = contents(tmp_path), dict(os.environ)

    for argv in (["alpha"], ["alpha", "--json"], [], ["--json"]):
        assert main(["config", "check", *argv]) == 0
        output = capsys.readouterr().out
        assert [name for name, secret in SECRETS.items() if secret in output] == []
    # Nothing created (no cache or workspace), no variable written, no client constructed.
    assert (contents(tmp_path), dict(os.environ), sandbox) == (before, environment, [])
    payload = json.loads(load_application(select_configuration("alpha")).payload)
    assert payload["memory"]["vdb_config"]["api_key"] == SECRETS["vdb"]
    headers = payload["tools"]["mcp"]["servers"]["docs"]["headers"]
    assert headers == {"Authorization": f"Bearer {SECRETS['MCP_DOCS_TOKEN']}"}


def test_init_never_overwrites_reuses_directories_and_keeps_an_existing_default(
    tmp_path: Path, home: Path, capsys: pytest.CaptureFixture
) -> None:
    settings = home / "settings" / "settings.yaml"
    settings.parent.mkdir(parents=True)
    settings.write_text("# Personal settings.\ntheme: dark\n")
    notes = home / "configs" / "profiles" / "alpha" / "notes.txt"
    notes.parent.mkdir(parents=True)
    notes.write_text("keep")
    assert create("alpha", "alpha") == 0
    assert "alpha (set as the default bundle)" in capsys.readouterr().out
    # Appending keeps the other settings and their comments exactly.
    kept = "# Personal settings.\ntheme: dark\ndefault_bundle: alpha\n"
    assert (settings.read_text(), notes.read_text()) == (kept, "keep")

    # An existing bundle, or any profile it would write, refuses before anything changes.
    taken = profile(home, f"beta/{LAYOUT['voice']}")
    taken.parent.mkdir(parents=True)
    taken.write_text("keep: me\n")
    before = contents(tmp_path)
    for name, existing in (("alpha", home / "configs" / "bundles" / "alpha.yaml"), ("beta", taken)):
        assert create(name, "other") == 2
        assert f"Refusing to overwrite an existing file: {existing}" in capsys.readouterr().err
        assert contents(tmp_path) == before

    # Another bundle keeps the default and every settings byte; a non-ASCII ID survives.
    assert create("gamma", "助手-1") == 0
    assert "alpha (unchanged)" in capsys.readouterr().out
    assert settings.read_text() == kept
    assert load_application(select_configuration("gamma")).avatar.avatar.id == "助手-1"

    # Invalid names, IDs or settings fail before any file or directory exists.
    before = contents(tmp_path)
    for name, identity, message in (
        ("my-avatar.yaml", "x", "Bundle names use"),
        ("Delta", "x", "Bundle names use"),
        ("../delta", "x", "Bundle names use"),
        ("delta", " x", "fields: avatar.id"),
        # A line break YAML would fold into a space.
        ("delta", "a\x85b", "fields: avatar.id"),
    ):
        assert create(name, identity) == 2
        assert message in capsys.readouterr().err
        assert contents(tmp_path) == before
    settings.write_text("- not a mapping\n")
    before = contents(tmp_path)
    assert create("delta", "delta") == 2
    assert "Settings must be a mapping" in capsys.readouterr().err
    assert contents(tmp_path) == before


@pytest.mark.parametrize(
    ("failure", "code"),
    [("profile-write", 28), ("profile-directory", 13), ("settings-cancel", None), ("new-home", 5)],
)
def test_a_failed_init_removes_only_what_it_created(
    failure: str, code: int | None, tmp_path: Path, home: Path, capsys: pytest.CaptureFixture
) -> None:
    if failure != "new-home":
        # Content to keep: another bundle with its profiles, and settings without a default.
        assert create("other", "other") == 0
        (home / "settings" / "settings.yaml").write_text("# Mine.\ntheme: dark\n")
    capsys.readouterr()
    before = contents(tmp_path)
    real_open, real_mkdir, opened = Path.open, os.mkdir, []

    class FullDisk(io.StringIO):
        def write(self, text: str) -> int:
            raise OSError(errno.ENOSPC, "No space left on device")

    def full(path: Path, mode: str = "r", *args: object, **kwargs: object):
        if mode == "x":
            opened.append(path)
            if len(opened) == 3:
                # The bundle and one profile exist; this file exists before writing fails.
                real_open(path, mode, *args, **kwargs).close()
                return FullDisk()
        return real_open(path, mode, *args, **kwargs)

    def denied(path: object, *args: object, **kwargs: object) -> None:
        if Path(path) == home / "configs" / "profiles" / "new":
            raise OSError(errno.EACCES, "Permission denied")
        real_mkdir(path, *args, **kwargs)

    def unreplaceable(*args: object) -> None:
        if failure == "settings-cancel":
            raise KeyboardInterrupt  # Cancelled just before the settings commit.
        raise OSError(errno.EIO, "Input/output error")

    patch = {
        "profile-write": mock.patch.object(Path, "open", full),
        "profile-directory": mock.patch.object(os, "mkdir", denied),
    }.get(failure, mock.patch.object(os, "replace", unreplaceable))
    with patch:
        if code is None:
            with pytest.raises(KeyboardInterrupt):
                create("new", "new")
        else:
            assert create("new", "new") == 2
            assert f"errno={code}" in capsys.readouterr().err
    # Only the settings lock outlives a failure in a new home; the lock library keeps it.
    lock = {"application": None, "application/settings": None, LOCK: b""}
    assert contents(tmp_path) == before | (lock if failure == "new-home" else {})


def test_cancelling_init_after_the_settings_commit_keeps_the_bundle_it_made_default(
    home: Path,
) -> None:
    settings = home / "settings" / "settings.yaml"
    settings.parent.mkdir(parents=True)
    settings.write_text("theme: dark\n")
    replace = os.replace

    def interrupted(*args: object) -> None:
        replace(*args)
        raise KeyboardInterrupt

    with mock.patch.object(os, "replace", interrupted), pytest.raises(KeyboardInterrupt):
        create("alpha", "alpha")
    # The default names a complete bundle; the cancellation still reached the caller.
    assert yaml.safe_load(settings.read_text()) == {"theme": "dark", "default_bundle": "alpha"}
    assert load_application(select_configuration(None)).avatar.avatar.id == "alpha"


def test_concurrent_inits_never_both_become_the_default(home: Path) -> None:
    paths, read, replace = application_paths(), template.read_settings, os.replace
    reads, results, failures = [], {}, []
    beta_read = threading.Event()

    def counted(paths: object) -> dict:
        settings = read(paths)
        if threading.current_thread() is not threading.main_thread():
            reads.append(settings.get("default_bundle"))
            if len(reads) == 2:  # Validation, then beta's own look for a default: done.
                beta_read.set()
        return settings

    def create_beta() -> None:
        try:
            results["beta"] = create_bundle(paths, "beta", avatar_id="beta").default_bundle
        except BaseException as error:
            failures.append(error)

    beta = threading.Thread(target=create_beta)

    def racing(*args: object) -> None:
        if beta.ident is None:
            # Alpha is about to commit; beta has just found no default either.
            beta.start()
            assert beta_read.wait(HANG_GUARD)
        replace(*args)

    with mock.patch.object(template, "read_settings", counted):
        with mock.patch.object(os, "replace", racing):
            results["alpha"] = create_bundle(paths, "alpha", avatar_id="alpha").default_bundle
        beta.join(HANG_GUARD)
    assert (failures, beta.is_alive()) == ([], False)
    assert reads[1] is None  # Beta had found no default before alpha committed.
    assert results == {"alpha": "alpha", "beta": "alpha"}
    assert read(paths) == {"default_bundle": "alpha"}


def test_the_default_joins_settings_a_line_cannot_extend_and_keeps_their_values(home: Path) -> None:
    settings = home / "settings" / "settings.yaml"
    settings.parent.mkdir(parents=True)
    # Settings written as JSON: an appended line would break the mapping, so it is rewritten.
    settings.write_text('{"theme": "dark"}\n')
    assert create("alpha", "alpha") == 0
    assert yaml.safe_load(settings.read_text()) == {"theme": "dark", "default_bundle": "alpha"}


def test_named_references_and_init_targets_stay_inside_the_real_home(
    tmp_path: Path, home: Path, capsys: pytest.CaptureFixture
) -> None:
    assert create("alpha", "alpha") == 0
    configs, outside = home / "configs", tmp_path / "outside"
    outside.mkdir()
    # A home reached through an alias, and links that stay inside the home, are valid.
    alias = tmp_path / "alias"
    alias.symlink_to(home)
    (configs / "profiles" / "shared").symlink_to(configs / "profiles" / "alpha")
    beta = {
        "avatar": {"id": "beta"},
        "loop": LOOP,
        "profiles": {"voice": f"shared/{LAYOUT['voice']}"},
    }
    write(configs / "bundles" / "beta.yaml", beta)
    with mock.patch.dict(os.environ, {"ALPHAAVATAR_HOME": str(alias)}):
        assert main(["config", "check", "beta"]) == 0 and create("gamma", "gamma") == 0
    capsys.readouterr()

    # init checks each target against the directory loading accepts: profiles linked into
    # the bundles directory would create a default bundle that cannot load.
    (configs / "bundles" / "shared").mkdir()
    (configs / "profiles" / "zeta").symlink_to(configs / "bundles" / "shared")
    before = contents(tmp_path)
    assert create("zeta", "zeta") == 2
    assert (
        f"Refusing to create: {profile(home, f'zeta/{LAYOUT[SECTIONS[0]]}')} resolves outside"
        in (capsys.readouterr().err)
    )
    assert contents(tmp_path) == before
    (configs / "profiles" / "zeta").unlink()
    (configs / "bundles" / "shared").rmdir()

    # A bundle file or a profile directory linked out of the home is refused.
    bundle = configs / "bundles" / "alpha.yaml"
    shutil.copy(bundle, outside / "alpha.yaml")
    bundle.unlink()
    bundle.symlink_to(outside / "alpha.yaml")
    assert main(["config", "check", "alpha"]) == 2
    assert f"Bundle 'alpha': {bundle} resolves outside" in capsys.readouterr().err
    bundle.unlink()
    shutil.copy(outside / "alpha.yaml", bundle)
    shutil.move(configs / "profiles" / "alpha", outside / "profiles")
    (configs / "profiles" / "alpha").symlink_to(outside / "profiles")
    assert main(["config", "check", "alpha"]) == 2
    assert f"Bundle 'alpha': profiles.{SECTIONS[0]}: " in capsys.readouterr().err

    # init refuses targets that would resolve out of the home before writing anything.
    (configs / "profiles" / "delta").symlink_to(outside / "delta")
    (outside / "delta").mkdir()
    shutil.move(configs / "bundles", outside / "bundles")
    for name, link in (("delta", configs / "profiles" / "delta"), ("epsilon", configs / "bundles")):
        if name == "epsilon":
            link.symlink_to(outside / "bundles")
        before = contents(tmp_path)
        assert create(name, name) == 2
        assert "Refusing to create: " in capsys.readouterr().err
        assert contents(tmp_path) == before
    # An explicit file keeps its own rules wherever it is.
    write(outside / "single.yaml", {"avatar": {"id": "single"}, "loop": LOOP})
    assert main(["config", "check", str(outside / "single.yaml")]) == 0


def test_a_settings_lock_linked_to_the_settings_is_refused_and_init_leaves_nothing(
    tmp_path: Path, home: Path, capsys: pytest.CaptureFixture
) -> None:
    settings = home / "settings" / "settings.yaml"
    settings.parent.mkdir(parents=True)
    settings.write_text("theme: dark\n")
    # Opening a lock truncates its file; through this link, that would empty the settings.
    # Other link targets are refused by the shared lock (test_locked_directory.py).
    settings.with_name(".write.lock").symlink_to(settings)
    before = contents(tmp_path)
    assert create("alpha", "alpha") == 2
    assert "Refusing to lock settings through a symbolic link" in capsys.readouterr().err
    assert contents(tmp_path) == before
