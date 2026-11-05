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
"""Configuration commands: no Host, runner, model, client, workspace or log socket.

Styles only decorate already redacted, control-character cleaned text; JSON and redirected
output stay plain.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

from alphaavatar.core.log.records import clean
from alphaavatar.host.log.format import BOLD, DIM, GREEN, RED, RESET, use_color

SCOPE = "configuration and read-only path checks"


def _paint(text: str, style: str, color: bool) -> str:
    return f"{style}{text}{RESET}" if color else text


def _status(label: str, style: str, message: str, stream: TextIO) -> bool:
    color = use_color("auto", stream)
    # Text reports stand apart from the command line: one blank line before and after.
    print(f"\n{_paint(label, BOLD + style, color)}  {message}", file=stream)
    return color


def _lines(summary: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Aligned facts by layer, as bundles lay out their profiles; "" holds the selection.

    Plugins, tools and health are summarized, not listed raw.
    """
    from alphaavatar.host.configs import LAYERS

    plugins, tools, health = summary["plugins"], summary["plugins"]["tools"], summary["health"]
    stores = {}
    for name in ("memory", "persona"):
        store = plugins[name]
        details = [f"vdb: {store['vdb']}"] if store["vdb"] else []
        if switches := _switches(store, ("vdb",)):
            details.append(switches)
        stores[name] = _name(store["plugin"]) + (f"  ({'; '.join(details)})" if details else "")
    router = _name(plugins["router"]["plugin"])
    if switches := _switches(plugins["router"]):
        router += f"  ({switches})"
    vision = plugins["vision"]
    mcp = tools["mcp"]
    if mcp is not None:
        mcp = f"{mcp['plugin']}  ({mcp['servers']} server{'' if mcp['servers'] == 1 else 's'})"
    port = health["port"] if health["port"] is not None else "8081 (dev: free port)"
    runners = summary["inference"]
    parallel = [f"{method} x{workers}" for method, workers in runners.items() if workers > 1]
    inference = f"{len(runners)} runner{'' if len(runners) == 1 else 's'}" if runners else "none"
    if parallel:
        inference += f"  (workers: {', '.join(parallel)})"
    elif runners:
        inference += ", 1 worker each"
    source = summary["config"]
    config = f"bundle {source['bundle']}" if source["bundle"] else source["file"]
    config += "  (default)" if source["default"] else ""
    sections = {
        "host": {"rtc": plugins["rtc"], "health": f"{health['bind']}:{port}"},
        "runtime": {"inference": inference},
        "context": {"context": _name(plugins["context"])},
        "loop": {"loop": _name(plugins["loop"])},
        "voice": {
            "voice": "  ".join(f"{part}={_name(name)}" for part, name in plugins["voice"].items())
        },
        "vision": {"vision": f"on  (input: {vision['input']})" if vision["enabled"] else "off"},
        "status": {
            "status": _name(plugins["status"]["plugin"]) if plugins["status"]["enabled"] else "off"
        },
        "router": {"router": router},
        "character": {"character": _name(plugins["character"])},
        "memory": {"memory": stores["memory"]},
        "persona": {"persona": stores["persona"]},
        "tools": {
            "deepresearch": _name(tools["deepresearch"]),
            "rag": _name(tools["rag"]),
            "mcp": _name(mcp),
        },
    }
    layers: dict[str, dict[str, str]] = {
        "": {
            "config": config,
            "avatar_id": summary["avatar_id"],
            "home": summary["home"],
            "workspace": summary["workspace"],
        }
    }
    for section, layer in LAYERS.items():
        layers.setdefault(layer, {}).update(sections[section])
    return layers


def _name(plugin: str | None) -> str:
    return plugin if plugin is not None else "none"


def _switch(enabled: bool) -> str:
    return "on" if enabled else "off"


def _switches(section: dict[str, Any], skip: tuple[str, ...] = ()) -> str:
    """A plugin's processor switches, e.g. ``turn taking on, environment off``."""
    return ", ".join(
        f"{name.replace('_', ' ')} {_switch(value)}"
        for name, value in section.items()
        if name not in ("plugin", *skip)
    )


def _load(target: str | None, overrides: Sequence[str]):
    from alphaavatar.host.configs import (
        check_application_paths,
        check_capabilities,
        load_application,
        select_configuration,
        validate_plugin_settings,
    )
    from alphaavatar.host.configs.credentials import load_environment

    # The same .env and stored credentials start reads, for interpolated values.
    load_environment(overrides)
    source = select_configuration(target, overrides)
    config = load_application(source, overrides)
    check_application_paths(config)
    validate_plugin_settings(config)
    check_capabilities(config)
    return config, source


def check(target: str | None, overrides: Sequence[str], *, as_json: bool) -> int:
    from alphaavatar.host.configs import describe_error, describe_summary, format_failure

    try:
        summary = describe_summary(*_load(target, overrides))
    except Exception as error:
        if as_json:
            print(json.dumps({"valid": False, "error": describe_error(error)}, indent=2))
            return 2
        color = _status("ERROR", RED, f"{SCOPE} failed", sys.stderr)
        for line in format_failure(error).splitlines():
            # Code locations are auxiliary; the failing fields stay prominent.
            auxiliary = line.lstrip().startswith(("at ", "additional"))
            print(_paint(line, DIM, color) if auxiliary else line, file=sys.stderr)
        print(file=sys.stderr)
        return 2
    if as_json:
        print(json.dumps({"valid": True, **summary}, indent=2, ensure_ascii=False))
    else:
        layers = _lines(summary)  # Complete before printing anything.
        color = _status("OK", GREEN, f"{SCOPE} passed", sys.stdout)
        # Values share one column; facts of a layer are indented under its name.
        width = max(len(key) + 2 * bool(layer) for layer, facts in layers.items() for key in facts)
        for layer, facts in layers.items():
            if layer:
                print(f"    {_paint(layer, BOLD, color)}")
            indent = 2 * bool(layer)
            for key, value in facts.items():
                print(f"    {' ' * indent}{_paint(key.ljust(width - indent), DIM, color)}  {value}")
        print()
    return 0


def init(name: str, *, avatar_id: str) -> int:
    from alphaavatar.agents.env import init_env
    from alphaavatar.host.configs import (
        REQUIRED_ENVIRONMENT,
        application_paths,
        create_bundle,
        format_failure,
    )

    try:
        init_env()  # ALPHAAVATAR_HOME may come from the same .env that start reads.
        created = create_bundle(application_paths(), name, avatar_id=avatar_id)
    except FileExistsError as error:
        print(
            f"\nRefusing to overwrite an existing file: {clean(error.filename)}\n", file=sys.stderr
        )
        return 2
    except Exception as error:
        print(f"\nCannot create the configuration:\n{format_failure(error)}\n", file=sys.stderr)
        return 2
    root = Path(os.path.commonpath(created.profiles))
    layers = ", ".join(
        dict.fromkeys(str(path.parent.relative_to(root)) for path in created.profiles)
    )
    if created.default_bundle == name:
        default = f"{name} (set as the default bundle)"
    else:
        default = f"{clean(created.default_bundle)} (unchanged)"
    print(f"\nCreated bundle {name}")
    print(f"  bundle    {clean(str(created.bundle))}")
    print(f"  profiles  {clean(str(root))}  ({layers})")
    print(f"  default   {default}")
    print("Set these in the environment or .env (never in the files):")
    print("\n".join(f"  {key:<50} {use}" for key, use in REQUIRED_ENVIRONMENT))
    print("Next:")
    if _bare_package():
        print("  alphaavatar setup                 # installs capabilities; it creates a new")
        print(
            f"                                    # bundle with them, and {name} stays as written"
        )
        print(f"  alphaavatar config check {name}    # names what {name} needs installed\n")
        return 0
    print(f"  alphaavatar dev {name}             # start; validates the configuration first")
    print(f"  alphaavatar config check {name}    # optional: validate without starting\n")
    return 0


def _bare_package() -> bool:
    """An installed base package with no setup environment: plugins are yet to be installed."""
    from alphaavatar.host.setup.environment import Installation, SetupError

    try:
        Installation.running()
    except SetupError:
        return False
    return sys.prefix == sys.base_prefix
