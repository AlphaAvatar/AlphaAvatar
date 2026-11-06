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

Text reports go through the shared renderer (``cli.render``), over already redacted text;
JSON stays plain.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from alphaavatar.core.log.records import clean
from alphaavatar.host.cli.render import Report, home_relative

SCOPE = "Configuration and read-only path checks"


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

    # The same .env and stored credentials start reads, for interpolated values, and the
    # default bundle from the same read of the settings.
    settings = load_environment(overrides)
    source = select_configuration(target, overrides, settings)
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
        report = Report(sys.stderr)
        report.title("Config check")
        report.status("ERROR", f"{SCOPE} failed")
        report.write()
        report.verbatim(format_failure(error))  # The failing fields stay whole and prominent.
        report.write()
        return 2
    if as_json:
        print(json.dumps({"valid": True, **summary}, indent=2, ensure_ascii=False))
        return 0
    layers = _lines(summary)  # Complete before printing anything.
    report = Report()
    report.title("Config check")
    report.status("OK", f"{SCOPE} passed")
    # Values share one column; the selection, then the facts of each profile layer.
    column = report.column([key for facts in layers.values() for key in facts])
    for layer, facts in layers.items():
        report.heading(layer or "Configuration")
        for key, value in facts.items():
            report.row(key, value, column=column)
    report.write()
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
        report = Report(sys.stderr)
        report.title("Config init")
        report.status("ERROR", f"Refusing to overwrite an existing file: {error.filename}")
        report.write()
        return 2
    except Exception as error:
        report = Report(sys.stderr)
        report.title("Config init")
        report.status("ERROR", "Cannot create the configuration")
        report.write()
        report.verbatim(format_failure(error))
        report.write()
        return 2
    root = Path(os.path.commonpath(created.profiles))
    default = name
    if created.default_bundle != name:
        default = f"{clean(created.default_bundle)} (unchanged)"
    report = Report()
    report.title("Config init")
    report.status("OK", "Bundle created")
    report.heading("Configuration")
    facts = {"Bundle": name, "Profiles": home_relative(root), "Default": default}
    column = report.column(list(facts))
    for key, value in facts.items():
        report.row(key, value, column=column)
    # Their names only: they are set in the environment or .env, never in the files.
    report.heading("Required credentials")
    for names, _ in REQUIRED_ENVIRONMENT:
        report.row(" · ".join(names.split(", ")))
    report.heading("Next")
    if _bare_package():
        # Setup installs the capabilities in a new bundle; this one stays as written, and
        # config check names what it needs installed.
        report.command("alphaavatar setup")
        report.command(f"alphaavatar config check {name}")
    else:
        # Checked, then diagnosed, before anything starts.
        report.command(f"alphaavatar config check {name}")
        report.command(f"alphaavatar doctor {name}")
    report.write()
    return 0


def _bare_package() -> bool:
    """An installed base package with no setup environment: plugins are yet to be installed."""
    from alphaavatar.host.setup.environment import Installation, SetupError

    try:
        Installation.running()
    except SetupError:
        return False
    return sys.prefix == sys.base_prefix
