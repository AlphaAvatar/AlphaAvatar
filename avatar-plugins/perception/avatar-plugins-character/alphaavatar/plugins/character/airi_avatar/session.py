# Copyright 2025 AlphaAvatar project
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
import json
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from alphaavatar.agents.character import CharacterTransport, VirtualCharacterSession
from alphaavatar.core.cleanup import wait_for_cleanup

from .config import AiriConfig

if TYPE_CHECKING:
    from playwright.async_api import (
        Browser,
        BrowserContext,
        Page,
        Playwright,
        PlaywrightContextManager,
    )


class AiriCharacterSession(VirtualCharacterSession):
    """Own a browser and scoped transport, never an inference worker or a second audio path."""

    def __init__(self, *, transport: CharacterTransport, config: AiriConfig) -> None:
        self._transport = transport
        self._config = config

        self._driver: PlaywrightContextManager | None = None
        self._driver_start: asyncio.Task[Playwright] | None = None
        self._browser: Browser | None = None
        self._browser_start: asyncio.Task[None] | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._start_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._monitor: asyncio.Task[None] | None = None
        self._failure: RuntimeError | None = None
        self._failed = asyncio.Event()
        self._stage = "created"

    @staticmethod
    def _observe(task: asyncio.Future[object]) -> None:
        if not task.cancelled():
            task.exception()

    def _fail(self, reason: str) -> None:
        if self._close_task is None and self._failure is None:
            self._failure = RuntimeError(reason)
            self._failed.set()

    def _browser_lost(self, *_) -> None:
        self._fail("Character browser disconnected unexpectedly")

    def _page_lost(self, *_) -> None:
        self._fail("Character page closed or crashed unexpectedly")

    async def _monitor_transport(self) -> None:
        try:
            await self._transport.wait_failed()
        except asyncio.CancelledError:
            if self._close_task is None:
                self._fail("Character transport monitor cancelled unexpectedly")
            raise
        except Exception:
            self._fail("Character transport failed")
        else:
            self._fail("Character transport failure monitor exited unexpectedly")

    def _check_open(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("Character session is closing or closed")
        if self._failure is not None:
            raise self._failure

    async def _wait_ready(self) -> None:
        ready = asyncio.create_task(self._transport.wait_ready(), name="character_ready")
        failed = asyncio.create_task(self._failed.wait(), name="character_start_failure")
        try:
            await asyncio.wait((ready, failed), return_when=asyncio.FIRST_COMPLETED)
            self._check_open()
            await ready
        finally:
            for task in (ready, failed):
                if not task.done():
                    task.cancel()
            await asyncio.gather(ready, failed, return_exceptions=True)

    async def _launch_browser(self, playwright: Playwright) -> None:
        self._browser = await playwright.chromium.launch(
            headless=True,
            chromium_sandbox=self._config.chromium_sandbox,
            executable_path=self._config.executable_path,
            timeout=self._config.startup_timeout * 1000,
            args=["--autoplay-policy=no-user-gesture-required", "--mute-audio"],
        )

    async def _start(self) -> None:
        self._check_open()

        # Importing or selecting a disabled Character must not initialize Playwright.
        from playwright.async_api import async_playwright

        async with asyncio.timeout(self._config.startup_timeout):
            self._stage = "transport"
            await self._transport.on_start()

            self._check_open()
            connection = self._transport.connection
            if connection.transport != "livekit":
                raise ValueError("AIRI currently requires the LiveKit Character transport")

            self._monitor = asyncio.create_task(
                self._monitor_transport(), name="character_transport_monitor"
            )
            self._monitor.add_done_callback(self._observe)

            # Driver creation may spawn a subprocess before returning its handle. Keep
            # acquisition owned and settle it before teardown, even if startup is cancelled.
            self._stage = "driver"
            self._driver = async_playwright()
            self._driver_start = asyncio.create_task(self._driver.start(), name="character_driver")
            self._driver_start.add_done_callback(self._observe)
            playwright = await asyncio.shield(self._driver_start)
            self._check_open()
            self._stage = "browser"
            self._browser_start = asyncio.create_task(
                self._launch_browser(playwright), name="character_browser"
            )
            self._browser_start.add_done_callback(self._observe)
            await asyncio.shield(self._browser_start)
            self._check_open()
            self._browser.on("disconnected", self._browser_lost)
            self._stage = "context"
            self._context = await self._browser.new_context(
                viewport={"width": self._config.video_width, "height": self._config.video_height},
                service_workers="block",
                accept_downloads=False,
                extra_http_headers={"Referer": self._config.frontend_url},
            )
            self._check_open()
            parsed = urlsplit(self._config.frontend_url)
            launch = {
                "origin": f"{parsed.scheme}://{parsed.netloc}",
                "path": parsed.path or "/",
                "query": {
                    "livekitUrl": connection.url,
                    "livekitToken": connection.token,
                    "agentIdentity": connection.agent_device_id,
                },
            }
            # The pinned frontend reads route.query. Populate browser-local history before
            # Vue starts; never put the credential in the HTTP navigation URL or Referer.
            await self._context.add_init_script(
                "(() => { const c = " + json.dumps(launch) + "; "
                "if (location.origin === c.origin && location.pathname === c.path) { "
                "history.replaceState(null, '', c.path + '?' + new URLSearchParams(c.query)); "
                "} })();"
            )
            self._check_open()
            self._page = await self._context.new_page()
            self._check_open()
            self._page.on("close", self._page_lost)
            self._page.on("crash", self._page_lost)

            # Browser console/page errors can contain credentials. Do not forward them.
            self._stage = "navigation"
            response = await self._page.goto(
                self._config.frontend_url,
                wait_until="domcontentloaded",
                timeout=self._config.startup_timeout * 1000,
            )
            if response is None or not response.ok:
                raise RuntimeError("Character frontend navigation failed")

            landed = urlsplit(self._page.url)
            if (landed.scheme, landed.netloc, landed.path or "/") != (
                parsed.scheme,
                parsed.netloc,
                parsed.path or "/",
            ):
                raise RuntimeError("Character frontend redirected away from its configured route")

            self._stage = "readiness"
            await self._wait_ready()
            await self._page.evaluate("history.replaceState(null, '', location.pathname)")
            self._check_open()

    async def on_start(self) -> None:
        self._check_open()
        if self._start_task is None:
            self._start_task = asyncio.create_task(self._start(), name="character_start")
            self._start_task.add_done_callback(self._observe)

        try:
            await asyncio.shield(self._start_task)
            self._check_open()
        except BaseException as original:
            try:
                await self.on_stop()
            except BaseException as cleanup:
                if not isinstance(original, Exception):
                    raise original from cleanup
                raise RuntimeError("Character startup and cleanup failed") from cleanup
            if not isinstance(original, Exception):
                raise
            # Playwright error details may include a credential-bearing browser URL.
            raise RuntimeError(
                f"Character startup failed at {self._stage} ({type(original).__name__})"
            ) from None

    async def wait_failed(self) -> None:
        await self._failed.wait()
        raise RuntimeError("Character presentation failed") from self._failure

    async def _close_step(
        self, operation: Callable[[], Awaitable[object]], label: str, errors: list[Exception]
    ) -> None:
        try:
            async with asyncio.timeout(self._config.close_timeout):
                await operation()
        except (Exception, asyncio.CancelledError) as error:
            message = f"Character {label} cleanup failed ({type(error).__name__})"
            errors.append(RuntimeError(message))

    async def _close(self) -> None:
        for task in (self._start_task, self._monitor):
            if task is not None and not task.done() and not task.cancelling():
                task.cancel()
        await asyncio.gather(
            *(t for t in (self._start_task, self._monitor) if t is not None), return_exceptions=True
        )

        # Cancelling Playwright during subprocess acquisition can lose the pipe owner.
        # This local acquisition is joined, not abandoned at the presentation deadline.
        for task in (self._driver_start, self._browser_start):
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)

        errors: list[Exception] = []
        if self._context is not None:
            await self._close_step(self._context.close, "context", errors)
        if self._browser is not None:
            await self._close_step(self._browser.close, "browser", errors)
        if self._driver is not None:
            await self._close_step(self._driver.__aexit__, "driver", errors)

        await self._close_step(self._transport.on_stop, "transport", errors)
        self._context = self._browser = self._page = self._driver = None
        if errors:
            raise ExceptionGroup("Character shutdown failed", errors)

    async def on_stop(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="character_close")
            self._close_task.add_done_callback(self._observe)
        await wait_for_cleanup(self._close_task)
