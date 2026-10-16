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

import asyncio
import logging
import sys
from collections.abc import Sequence


def run(path: str, overrides: Sequence[str], *, devmode: bool) -> int:
    logging.basicConfig(
        level=logging.DEBUG if devmode else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        from alphaavatar.agents.env import init_env
        from alphaavatar.host.configs.loader import load_application

        init_env()
        config = load_application(path, overrides)
    except (OSError, ValueError, ImportError) as error:
        # Pydantic's default rendering includes input values, possibly credentials.
        from pydantic import ValidationError

        if isinstance(error, ValidationError):
            locations = ", ".join(
                ".".join(str(part) for part in item["loc"]) for item in error.errors()
            )
            print(f"Invalid application configuration at: {locations}", file=sys.stderr)
        else:
            print(
                f"Cannot load application configuration ({type(error).__name__}): check the file, overrides, environment and installed extras",
                file=sys.stderr,
            )
        return 2

    async def serve() -> None:
        from alphaavatar.host.application.application import AvatarHost
        from alphaavatar.host.application.signals import shutdown_signals

        host = AvatarHost(config, devmode=devmode)
        with shutdown_signals(host.stop_event):
            await host.run()

    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        print(
            f"AlphaAvatar Host stopped ({type(error).__name__}); inspect service and execution status",
            file=sys.stderr,
        )
        return 1
    return 0
