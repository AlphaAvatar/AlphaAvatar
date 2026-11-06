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
    setup = commands.add_parser(
        "setup",
        help="Install what a bundle needs, check it, then enable it: an existing bundle, or "
        "one asked for part by part from the reference configuration",
    )
    setup.add_argument(
        "bundle",
        nargs="?",
        help="An existing bundle, as config init makes it or as edited: no questions, the "
        "credentials from the environment. Omitted: asked in a terminal",
    )
    setup.add_argument("--name", help="The new bundle's name, when asked (default: avatar)")
    setup.add_argument("--avatar-id", help="The new bundle's Avatar ID (default: the name)")
    setup.add_argument(
        "--artifacts",
        metavar="DIR|URL",
        help="Where this build's own wheels are, if not its release: the CI build's directory",
    )
    setup.add_argument(
        "--plan", action="store_true", help="Print the install plan as JSON; change nothing"
    )
    doctor = commands.add_parser(
        "doctor",
        help="Diagnose the installation and a configuration: static checks, then the runtime "
        "diagnosis on fixed samples, each scenario in rounds (once agreed, or authorized)",
    )
    configured(doctor, json_output=True)
    doctor.add_argument("--list", action="store_true", help="List the checks without running")
    doctor.add_argument(
        "--no-metrics",
        action="store_true",
        help="Static checks alone: no runtime diagnosis, no runner, nothing contacted",
    )
    doctor.add_argument(
        "--rounds",
        type=int,
        default=5,
        metavar="N",
        help="How many times each scenario runs, each in a session of its own (default 5)",
    )

    args = parser.parse_args(argv)
    if "=" in (getattr(args, "config", None) or ""):
        # KEY=VALUE is always an override, never a bundle or file: the default bundle applies.
        args.overrides.insert(0, args.config)
        args.config = None
    for item in getattr(args, "overrides", ()):
        if "=" not in item or not item.partition("=")[0]:
            parser.error("Configuration overrides must use KEY=VALUE")

    if args.command == "doctor" and not 1 <= args.rounds <= 50:
        parser.error("--rounds takes 1 to 50")
    if args.command == "setup":
        if args.bundle is not None and (args.name or args.avatar_id):
            parser.error("--name and --avatar-id name a new bundle; an existing one has both")
        from .commands.setup import setup as run_setup

        return run_setup(args)
    if args.command in ("dev", "start"):
        from .commands.run import run

        return run(args.config, args.overrides, devmode=args.command == "dev")
    if args.command == "doctor":
        if args.list and (args.config is not None or args.overrides):
            parser.error("--list takes no configuration")
        from .commands.doctor import doctor

        return doctor(
            args.config,
            args.overrides,
            as_json=args.json,
            listing=args.list,
            metrics=not args.no_metrics,
            rounds=args.rounds,
        )

    from .commands import config as configuration

    if args.action == "check":
        return configuration.check(args.config, args.overrides, as_json=args.json)
    return configuration.init(args.name, avatar_id=args.avatar_id)
