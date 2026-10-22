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
    parser = argparse.ArgumentParser(prog="alphaavatar", description="Run an AlphaAvatar Host.")
    parser.add_argument("--version", action="version", version=f"AlphaAvatar {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("dev", "start"):
        run = commands.add_parser(command, help=f"Run the Host in {command} mode")
        run.add_argument("config", help="Application YAML or JSON file")
        run.add_argument("overrides", nargs="*", metavar="KEY=VALUE")

    args = parser.parse_args(argv)
    for item in args.overrides:
        if "=" not in item or not item.partition("=")[0]:
            parser.error("Configuration overrides must use KEY=VALUE")

    from .commands.run import run

    return run(args.config, args.overrides, devmode=args.command == "dev")
