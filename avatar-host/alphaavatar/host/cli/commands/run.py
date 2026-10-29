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

from alphaavatar.core.log.diagnostics import format_error


def run(path: str, overrides: Sequence[str], *, devmode: bool) -> int:
    logs = None
    stage = "configure Host logging"
    result = 2
    try:
        from alphaavatar.host.log.runtime import HostLog

        logs = HostLog(devmode=devmode)
        stage = "import configuration loader"
        from alphaavatar.agents.env import init_env
        from alphaavatar.host.configs.loader import load_application

        stage = "load environment"
        init_env()
        logs.refresh_secrets()

        stage = "load application configuration"
        config = load_application(path, overrides)

        stage = "prepare application paths"
        from alphaavatar.core.workspace import (
            check_legacy_identity,
            check_workspace_continuity,
            prepare_application,
            prepare_workspace,
        )

        check_workspace_continuity(config.workspace, config.previous_workspace_roots)
        if config.workspace == config.paths.workspace(config.avatar.avatar.id):
            check_legacy_identity(config.paths.avatars_dir, config.avatar.avatar.id)
        prepare_application(config.paths)
        prepare_workspace(config.workspace)

        stage = "activate Host logging"
        logs.activate(config.host.log, workspace=str(config.workspace.root))
        result = 1

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

            logging.getLogger(__name__).info("Host stopped; owned resources settled")

        asyncio.run(serve())
        result = 0
    except KeyboardInterrupt:
        result = 130
    except Exception as error:
        diagnostic = format_error(error, details=devmode)
        try:
            if logs is None:
                raise RuntimeError("Host logging is unavailable")
            if not logs.active:
                logs.activate()
            logging.getLogger(__name__).error("Cannot %s\n%s", stage, diagnostic)
        except Exception:
            print(f"Cannot {stage}:\n{diagnostic}", file=sys.stderr)
    finally:
        if logs is not None:
            try:
                # The asyncio loop and all child producers have already settled.
                logs.close()
            except Exception as error:
                print(f"Cannot close Host logging:\n{format_error(error)}", file=sys.stderr)
                if result == 0:
                    result = 1
    return result
