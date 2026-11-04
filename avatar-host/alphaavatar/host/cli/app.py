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
from __future__ import annotations

import argparse
from collections.abc import Sequence

from alphaavatar.host.version import __version__


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="alphaavatar", description="Run and configure an AlphaAvatar Host."
    )
    parser.add_argument("--version", action="version", version=f"AlphaAvatar {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    def configured(command: argparse.ArgumentParser, *, json_output: bool) -> None:
        command.add_argument(
            "config",
            nargs="?",
            help="Bundle name, or a YAML/JSON file path; omitted: the default bundle",
        )
        command.add_argument("overrides", nargs="*", metavar="KEY=VALUE")
        if json_output:
            command.add_argument("--json", action="store_true", help="Print JSON for tools")

    for command in ("dev", "start"):
        configured(
            commands.add_parser(command, help=f"Run the Host in {command} mode"), json_output=False
        )
    config = commands.add_parser("config", help="Create or check application configuration")
    actions = config.add_subparsers(dest="action", required=True)
    init = actions.add_parser("init", help="Create a minimal bundle and its profiles")
    init.add_argument("name", help="Bundle name: lowercase letters, digits, '-' or '_'")
    init.add_argument("--avatar-id", required=True, help="Stable Avatar identifier")
    configured(
        actions.add_parser("check", help="Validate a configuration without starting anything"),
        json_output=True,
    )
    doctor = commands.add_parser(
        "doctor",
        help="Diagnose the installation and a configuration: static checks, then a temporary "
        "session on fixed samples (external services only with host.doctor.external_services)",
    )
    configured(doctor, json_output=True)
    doctor.add_argument("--list", action="store_true", help="List the checks without running")

    args = parser.parse_args(argv)
    if "=" in (getattr(args, "config", None) or ""):
        # KEY=VALUE is always an override, never a bundle or file: the default bundle applies.
        args.overrides.insert(0, args.config)
        args.config = None
    for item in getattr(args, "overrides", ()):
        if "=" not in item or not item.partition("=")[0]:
            parser.error("Configuration overrides must use KEY=VALUE")

    if args.command in ("dev", "start"):
        from .commands.run import run

        return run(args.config, args.overrides, devmode=args.command == "dev")
    if args.command == "doctor":
        if args.list and (args.config is not None or args.overrides):
            parser.error("--list takes no configuration")
        from .commands.doctor import doctor

        return doctor(args.config, args.overrides, as_json=args.json, listing=args.list)

    from .commands import config as configuration

    if args.action == "check":
        return configuration.check(args.config, args.overrides, as_json=args.json)
    return configuration.init(args.name, avatar_id=args.avatar_id)
