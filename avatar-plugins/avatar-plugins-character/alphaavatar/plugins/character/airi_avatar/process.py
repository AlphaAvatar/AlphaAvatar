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
import asyncio
import os
from contextlib import suppress
from pathlib import Path

from ..log import logger

try:
    from playwright.async_api import Browser, Page, async_playwright
except Exception:
    logger.info("[AIRI] Installing Chromium for Playwright...")
    import subprocess

    subprocess.run(["playwright", "install", "chromium"], check=True)
    from playwright.async_api import Browser, Page, async_playwright


class AiriProcess:
    def __init__(self, repo_dir: Path, port: int) -> None:
        self._repo_dir = repo_dir
        self._port = port
        self._proc: asyncio.subprocess.Process | None = None
        self._browser_task: asyncio.Task | None = None

    async def start(
        self,
        livekit_url: str,
        livekit_token: str,
        agent_identity: str,
        avatar_identity: str,
    ) -> None:
        if not self._proc or self._proc.returncode is not None:
            env = os.environ.copy()
            env["VITE_AIRI_LIVEKIT_URL"] = livekit_url
            env["VITE_AIRI_LIVEKIT_TOKEN"] = livekit_token
            env["VITE_AIRI_AGENT_IDENTITY"] = agent_identity
            env["VITE_AIRI_AVATAR_IDENTITY"] = avatar_identity
            env["AIRI_PORT"] = str(self._port)

            stage_web_dir = self._repo_dir / "apps" / "stage-web"

            self._proc = await asyncio.create_subprocess_exec(
                "pnpm",
                "dev",
                "--port",
                str(self._port),
                cwd=str(stage_web_dir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            asyncio.create_task(self._log_output())

        if self._browser_task is None or self._browser_task.done():
            self._browser_task = asyncio.create_task(self._run_headless_browser())

    async def _log_output(self):
        assert self._proc and self._proc.stdout
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                break
            logger.info(f"[AIRI frontend] {line.decode().rstrip()}")

    async def _wait_for_server_ready(self, timeout: float = 120.0):
        import aiohttp

        url = f"http://127.0.0.1:{self._port}/"
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout

        async with aiohttp.ClientSession() as session:
            while True:
                if loop.time() > deadline:
                    raise TimeoutError(f"AIRI dev server not ready on {url} within {timeout}s")

                try:
                    async with session.get(url) as resp:
                        if resp.status < 500:
                            logger.info(f"[AIRI] Dev server ready on {url} (status={resp.status})")
                            return
                except Exception:
                    pass

                await asyncio.sleep(0.5)

    async def _run_headless_browser(self):
        try:
            await self._wait_for_server_ready()

            async with async_playwright() as p:
                browser: Browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--autoplay-policy=no-user-gesture-required",
                        "--use-fake-ui-for-media-stream",
                        "--use-fake-device-for-media-stream",
                        "--mute-audio",
                    ],
                )
                page: Page = await browser.new_page()

                page.on(
                    "console",
                    lambda msg: logger.info(f"[console] {msg.type}: {msg.text}")
                    if msg.type == "log"
                    else None,
                )

                page.on("pageerror", lambda exc: logger.error(f"[pageerror] {exc}"))

                page.on(
                    "requestfailed",
                    lambda req: logger.warning(
                        f"[requestfailed] {req.method} {req.url} -> {req.failure}"
                    ),
                )

                url = f"http://127.0.0.1:{self._port}/livekit-avatar"
                logger.info(f"[AIRI] Opening headless page: {url}")
                await page.goto(url, wait_until="networkidle")

                try:
                    state = await page.evaluate(
                        "async () => { const ctx = new AudioContext(); return ctx.state; }"
                    )
                    logger.info(f"[AIRI] AudioContext state in page after goto: {state}")
                except Exception:
                    logger.exception("[AIRI] Failed to check AudioContext state")

                while True:
                    await asyncio.sleep(3600)

        except asyncio.CancelledError:
            logger.info("[AIRI] Headless browser task cancelled")
            raise
        except Exception:
            logger.exception("[AIRI] Headless browser task crashed")
        finally:
            logger.info("[AIRI] Headless browser task finished")

    async def stop(self):
        if self._browser_task and not self._browser_task.done():
            self._browser_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._browser_task
        self._browser_task = None
