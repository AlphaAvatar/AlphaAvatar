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
import sys
from collections.abc import Sequence
from typing import Any, TextIO

from alphaavatar.core.log.diagnostics import format_error
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


def _lines(summary: dict[str, Any]) -> dict[str, str]:
    """One aligned line per fact; plugins, tools and health are summarized, not listed raw."""
    plugins, tools, health = summary["plugins"], summary["plugins"]["tools"], summary["health"]
    memory, persona = plugins["memory"], plugins["persona"]
    stores = {}
    for name, store in (("memory", memory), ("persona", persona)):
        details = [f"vdb: {store['vdb']}"] if store["vdb"] else []
        if "speaker" in store:
            details += [f"speaker {_switch(store['speaker'])}, face {_switch(store['face'])}"]
        stores[name] = _name(store["plugin"]) + (f"  ({'; '.join(details)})" if details else "")
    enabled = [name for name in ("deepresearch", "rag") if tools[name] is not None]
    if (mcp := tools["mcp"]) is not None:
        enabled.append(f"mcp ({mcp['servers']} server{'' if mcp['servers'] == 1 else 's'})")
    port = health["port"] if health["port"] is not None else "8081 (dev: free port)"
    return {
        "avatar_id": summary["avatar_id"],
        "home": summary["home"],
        "workspace": summary["workspace"],
        "rtc": plugins["rtc"],
        "loop": _name(plugins["loop"]),
        "voice": "  ".join(f"{part}={_name(name)}" for part, name in plugins["voice"].items()),
        "router": _name(plugins["router"]),
        "character": _name(plugins["character"]),
        **stores,
        "tools": ", ".join(enabled) or "none",
        "health": f"{health['bind']}:{port}",
    }


def _name(plugin: str | None) -> str:
    return plugin if plugin is not None else "none"


def _switch(enabled: bool) -> str:
    return "on" if enabled else "off"


def _load(path: str, overrides: Sequence[str]):
    from alphaavatar.agents.env import init_env
    from alphaavatar.host.configs.loader import check_application_paths, load_application

    init_env()  # The same .env the start command reads for <ENV_VAR> placeholders.
    config = load_application(path, overrides)
    check_application_paths(config)
    return config


def check(path: str, overrides: Sequence[str], *, as_json: bool) -> int:
    from alphaavatar.host.configs.view import describe_error, describe_summary

    try:
        summary = describe_summary(_load(path, overrides))
    except Exception as error:
        if as_json:
            print(json.dumps({"valid": False, "error": describe_error(error)}, indent=2))
            return 2
        color = _status("ERROR", RED, f"{SCOPE} failed", sys.stderr)
        for line in format_error(error).splitlines():
            # Code locations are auxiliary; the failing fields stay prominent.
            auxiliary = line.lstrip().startswith(("at ", "additional"))
            print(_paint(line, DIM, color) if auxiliary else line, file=sys.stderr)
        print(file=sys.stderr)
        return 2
    if as_json:
        print(json.dumps({"valid": True, **summary}, indent=2, ensure_ascii=False))
    else:
        color = _status("OK", GREEN, f"{SCOPE} passed", sys.stdout)
        lines = _lines(summary)
        width = max(map(len, lines))
        for key, value in lines.items():
            print(f"    {_paint(key.ljust(width), DIM, color)}  {value}")
        print()
    return 0


def init(path: str, *, avatar_id: str) -> int:
    from alphaavatar.host.configs.template import REQUIRED_ENVIRONMENT, write_template

    try:
        target = write_template(path, avatar_id=avatar_id)
    except FileExistsError:
        print(f"\nRefusing to overwrite an existing file: {clean(path)}\n", file=sys.stderr)
        return 2
    except Exception as error:
        print(f"\nCannot create the configuration:\n{format_error(error)}\n", file=sys.stderr)
        return 2
    print(f"\nCreated {clean(str(target))}")
    print("Set these in the environment or .env (never in the file):")
    print("\n".join(f"  {name:<50} {use}" for name, use in REQUIRED_ENVIRONMENT))
    print("Next:")
    print(f"  alphaavatar dev {clean(path)}             # start; validates the file first")
    print(f"  alphaavatar config check {clean(path)}    # optional: validate without starting\n")
    return 0
