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

from collections.abc import Callable
from typing import Any

from aiohttp import web

from alphaavatar.core.lifecycle import LifecycleComponent

from .config import HealthConfig


class HealthServer(LifecycleComponent):
    def __init__(
        self,
        config: HealthConfig,
        *,
        devmode: bool,
        ready: Callable[[], bool],
        status: Callable[[], dict[str, Any]],
    ) -> None:
        self._config = config
        self._devmode = devmode
        self._ready = ready
        self._status = status

        self._runner: web.AppRunner | None = None
        self._closed = False
        self.port = 0

    async def _live(self, _: web.Request) -> web.Response:
        return web.Response(
            text="OK" if not self._closed else "Stopped", status=200 if not self._closed else 503
        )

    async def _readiness(self, _: web.Request) -> web.Response:
        ready = not self._closed and self._ready()
        return web.Response(text="OK" if ready else "Not ready", status=200 if ready else 503)

    async def _state(self, _: web.Request) -> web.Response:
        return web.json_response(self._status())

    async def on_start(self) -> None:
        if self._closed or self._runner is not None:
            raise RuntimeError("Health server can only start once")

        app = web.Application()
        app.add_routes(
            [
                web.get("/live", self._live),
                web.get("/ready", self._readiness),
                web.get("/status", self._state),
            ]
        )
        self._runner = web.AppRunner(app, access_log=None, shutdown_timeout=5.0)

        await self._runner.setup()

        port = self._config.port
        if port is None:
            port = 0 if self._devmode else 8081

        await web.TCPSite(self._runner, self._config.bind, port).start()
        self.port = self._runner.addresses[0][1]

    async def on_stop(self) -> None:
        self._closed = True
        if self._runner is not None:
            await self._runner.cleanup()
