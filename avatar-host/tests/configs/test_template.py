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
"""The default profiles `config init` writes and `alphaavatar setup` starts from: every public
setting written out, the reference configuration's values, no tool on, laid out to be edited."""

from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path
from unittest import mock

import pytest
import yaml

# Imported before any test: its libraries set process environment variables once loaded.
import alphaavatar.plugins.persona.factory  # noqa: F401
from alphaavatar.agents.configs import AvatarConfig
from alphaavatar.agents.runtime.plugin import AvatarModule, resolve_plugin
from alphaavatar.host.cli.app import main
from alphaavatar.host.configs import load_application, select_configuration
from alphaavatar.host.configs.bundles import LAYERS
from alphaavatar.host.configs.template import SECTIONS, TEMPLATES, _template
from alphaavatar.host.service.application.config import HostConfig
from alphaavatar.host.service.sessions.livekit.config import LiveKitConfig
from alphaavatar.plugins.status.config import StatusRuntimeConfig

REFERENCE = Path(__file__).resolve().parents[3] / "examples/agent_configs/roles/demo.yaml"
# Maps a person fills with entries of their own: written out once present, whatever they hold.
FREE = {"tasks", "extra", "input_options", "tool_policies", "servers", "methods", "vdb_config"}
PLUGINS = {
    "context": AvatarModule.CONTEXT,
    "loop": AvatarModule.LOOP,
    "router": AvatarModule.ROUTER,
    "memory": AvatarModule.MEMORY,
    "persona": AvatarModule.PERSONA,
}


def leaves(value: object, path: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    if isinstance(value, dict) and value and (not path or path[-1] not in FREE):
        return {leaf for key, item in value.items() for leaf in leaves(item, (*path, str(key)))}
    return {path}


def at(value: dict, path: tuple[str, ...]) -> dict:
    for key in path:
        value = value[key]
    return value


def schemas(section: str, raw: dict) -> list[tuple[tuple[str, ...], dict]]:
    """Each schema's settings for a profile, in full, by where they sit in it."""
    if section == "host":
        rtc = LiveKitConfig.model_validate(raw["rtc"]["init_config"]).model_dump(mode="json")
        return [
            ((), HostConfig.model_validate(raw).model_dump(mode="json")),
            (("rtc", "init_config"), rtc),
        ]
    avatar = AvatarConfig.model_validate({"avatar": {"id": "reference"}, section: raw})
    found = [((), avatar.model_dump(mode="json", exclude={"init_config"})[section])]
    if section in PLUGINS:
        settings = resolve_plugin(PLUGINS[section], raw["plugin"]).factory.settings(
            raw["init_config"]
        )
        found.append((("init_config",), settings.model_dump(mode="json")))
    if section == "status":
        settings = StatusRuntimeConfig.model_validate(raw["init_config"])
        found.append((("init_config",), settings.model_dump(mode="json")))
    return found


def effective(loaded: object) -> dict:
    """The configuration as start runs it, each plugin's settings in full; not where it lives."""
    payload = json.loads(loaded.payload)
    for section, module in PLUGINS.items():
        part = payload[section]
        part["init_config"] = (
            resolve_plugin(module, part["plugin"]).factory.settings(part["init_config"])
        ).model_dump(mode="json")
    status = payload["status"]
    status["init_config"] = StatusRuntimeConfig.model_validate(status["init_config"]).model_dump()
    rtc = payload["host"]["rtc"]
    rtc["init_config"] = LiveKitConfig.model_validate(rtc["init_config"]).model_dump(mode="json")
    del payload["application"], payload["avatar"]["workspace_root"]
    return payload


def lines(text: str) -> list[tuple[int, str]]:
    """Each setting's indentation and line, block scalars' text and comments left out; a blank
    line as (-1, "")."""
    found: list[tuple[int, str]] = []
    scalar = None  # The indentation of the key a block scalar's text follows.
    for line in text.splitlines():
        indent = len(line) - len(line.lstrip(" "))
        if scalar is not None and (not line.strip() or indent > scalar):
            continue
        scalar = None
        if not line.strip():
            found.append((-1, ""))
        elif not line.lstrip().startswith("#"):
            found.append((indent, line))
            if re.search(r":\s*[>|][+-]?\s*(#.*)?$", line):
                scalar = indent
    return found


def is_block(line: str) -> bool:
    """A key whose value is the mapping or list on the lines below it."""
    return bool(re.fullmatch(r"\s*[^#\s][^#]*:\s*(#.*)?", line))


def test_every_profile_writes_out_each_public_setting_of_its_schemas() -> None:
    assert set(SECTIONS) == set(LAYERS)
    # One file per section, the plugins' under their layer: none other ships.
    assert set(TEMPLATES.rglob("*.yaml")) == {_template(section) for section in LAYERS}
    assert _template("host") == TEMPLATES / "host.yaml"
    assert _template("memory") == TEMPLATES / "plugins/perception/memory.yaml"
    for section, text in SECTIONS.items():
        raw = yaml.safe_load(text)
        if section == "character":  # No implementation selected, none installable by setup.
            assert raw == {"plugin": None, "init_config": {}}
            continue
        for where, full in schemas(section, raw):
            written = leaves(at(raw, where))
            missing = sorted(
                ".".join((section, *where, *path))
                for path in leaves(full)
                if not any(path[: len(given)] == given for given in written)
            )
            assert missing == [], f"{section}: written without {missing}"


def test_the_profiles_run_the_reference_configuration_with_no_tool_on(home: Path) -> None:
    with mock.patch.dict(os.environ, {"COLUMNS": "200"}):
        assert main(["config", "init", "reference", "--avatar-id", "alphaavatar_demo"]) == 0
    written = effective(load_application(select_configuration("reference")))
    reference = effective(load_application(REFERENCE))
    # The reference shows every tool; here each is off, its settings kept to switch it on.
    tools = copy.deepcopy(reference["tools"])
    tools["deepresearch"]["plugin"] = tools["rag"]["plugin"] = None
    tools["mcp"] |= {"enabled": False, "servers": {}}
    assert written["tools"] == tools
    assert {k: v for k, v in written.items() if k != "tools"} == {
        k: v for k, v in reference.items() if k != "tools"
    }
    selected = AvatarConfig.model_validate(
        {k: v for k, v in written.items() if k != "host"}
    ).plugin_factories()
    assert not [location for location in selected if location.startswith("tools.")]
    # ENV memory is on, as the reference has it: Gemini, through its audio and video adapter.
    environment = written["memory"]["init_config"]["environment"]
    task = environment["provider"]["gateway"]["tasks"]["memory.env_delta"]
    assert (environment["enabled"], environment["include_audio"]) == (True, True)
    assert (task["provider"], task["model"], task["input_adapter"]) == (
        "google",
        "gemini-2.5-flash",
        "langchain_gemini",
    )


def test_the_profiles_are_laid_out_to_be_edited() -> None:
    for section, text in SECTIONS.items():
        assert text.endswith("\n") and not text.endswith("\n\n"), section
        assert "\t" not in text and "\n\n\n" not in text, section
        assert not [line for line in text.splitlines() if line != line.rstrip()], section
        found = lines(text)
        for index, (indent, line) in enumerate(found):
            if indent < 0:
                continue
            assert indent % 2 == 0, f"{section}: {line!r}"
            # A setting below its group sits two spaces in from it, never further.
            above = next((found[i][0] for i in range(index - 1, -1, -1) if found[i][0] >= 0), 0)
            assert indent <= above + 2, f"{section}: {line!r} is indented more than two spaces"
            # The sibling before it: blank lines and deeper settings between them.
            gap, before = False, index - 1
            while before >= 0 and (found[before][0] < 0 or found[before][0] > indent):
                gap |= found[before][0] < 0 and before == index - 1
                before -= 1
            if before < 0 or found[before][0] < indent:
                continue  # The first of its group.
            previous = found[before][1]
            if is_block(previous) and is_block(line):
                assert gap, f"{section}: no blank line between groups before {line!r}"
            elif not is_block(previous) and not is_block(line):
                assert found[index - 1][0] >= 0, f"{section}: a blank line inside {line!r}'s group"
    # What helps a person edit it stays, as written.
    voice = SECTIONS["voice"]
    assert "\n\nstt:\n" in voice and "\n\ntts:\n" in voice and "  instructions: >\n" in voice
    assert (
        "inference:\n" in SECTIONS["runtime"]
        and "  methods: {}  # Per runner, for example alphaavatar.voice.vad.silero: {workers: 2}\n"
        in SECTIONS["runtime"]
    )
    tools = SECTIONS["tools"]
    assert "TAVILY_API_KEY" in tools and "#   livekit-docs:\n" in tools
    assert "  servers: {}\n" in tools and "Bearer <MCP_DOCS_TOKEN>" in tools
    assert "GOOGLE_API_KEY" in SECTIONS["memory"]


@pytest.mark.parametrize("section", sorted(LAYERS))
def test_init_writes_each_profile_as_it_ships(section: str, home: Path) -> None:
    with mock.patch.dict(os.environ, {"COLUMNS": "200"}):
        assert main(["config", "init", "alpha", "--avatar-id", "alpha"]) == 0
    path = home / "configs" / "profiles" / "alpha" / LAYERS[section] / f"{section}.yaml"
    header, body = path.read_text().split("\n\n", 1)
    assert body == SECTIONS[section] and header.startswith("# AlphaAvatar")
    assert "`alphaavatar config check`" in header
