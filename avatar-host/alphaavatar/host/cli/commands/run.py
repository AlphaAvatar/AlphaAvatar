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

from alphaavatar.host.diagnostics import format_error


def run(path: str, overrides: Sequence[str], *, devmode: bool) -> int:
    logging.basicConfig(
        level=logging.DEBUG if devmode else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    stage = "import configuration loader"
    try:
        from alphaavatar.agents.env import init_env
        from alphaavatar.host.configs.loader import load_application

        stage = "load environment"
        init_env()
        stage = "load application configuration"
        config = load_application(path, overrides)
    except Exception as error:
        print(f"Cannot {stage}:\n{format_error(error, details=devmode)}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130

    async def serve() -> None:
        nonlocal stage
        stage = "import Host"
        from alphaavatar.host.application.application import AvatarHost
        from alphaavatar.host.application.signals import shutdown_signals

        stage = "construct Host"
        host = AvatarHost(config, devmode=devmode)
        stage = "run Host"
        with shutdown_signals(host.stop_event.set):
            await host.run()

    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        print(f"Cannot {stage}:\n{format_error(error, details=devmode)}", file=sys.stderr)
        return 1
    return 0
