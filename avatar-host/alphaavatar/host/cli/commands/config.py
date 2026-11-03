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
    return {
        "config": config,
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
        "inference": inference,
        "health": f"{health['bind']}:{port}",
    }


def _name(plugin: str | None) -> str:
    return plugin if plugin is not None else "none"


def _switch(enabled: bool) -> str:
    return "on" if enabled else "off"


def _load(target: str | None, overrides: Sequence[str]):
    from alphaavatar.agents.env import init_env
    from alphaavatar.host.configs import (
        check_application_paths,
        load_application,
        select_configuration,
    )

    init_env()  # The same .env the start command reads for <ENV_VAR> placeholders.
    source = select_configuration(target, overrides)
    config = load_application(source, overrides)
    check_application_paths(config)
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
        lines = _lines(summary)  # Complete before printing anything.
        color = _status("OK", GREEN, f"{SCOPE} passed", sys.stdout)
        width = max(map(len, lines))
        for key, value in lines.items():
            print(f"    {_paint(key.ljust(width), DIM, color)}  {value}")
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
    sections = ", ".join(path.stem for path in created.profiles)
    if created.default_bundle == name:
        default = f"{name} (set as the default bundle)"
    else:
        default = f"{clean(created.default_bundle)} (unchanged)"
    print(f"\nCreated bundle {name}")
    print(f"  bundle    {clean(str(created.bundle))}")
    print(f"  profiles  {clean(str(created.profiles[0].parent))}  ({sections})")
    print(f"  default   {default}")
    print("Set these in the environment or .env (never in the files):")
    print("\n".join(f"  {key:<50} {use}" for key, use in REQUIRED_ENVIRONMENT))
    print("Next:")
    print(f"  alphaavatar dev {name}             # start; validates the configuration first")
    print(f"  alphaavatar config check {name}    # optional: validate without starting\n")
    return 0
