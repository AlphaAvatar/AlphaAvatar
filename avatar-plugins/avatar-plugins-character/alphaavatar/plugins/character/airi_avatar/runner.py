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
import json
import os
import threading
import urllib.parse
from collections.abc import Coroutine
from concurrent.futures import Future
from pathlib import Path
from typing import Any, TypeVar

from livekit.agents.inference_runner import _InferenceRunner

from ..enum import RunnerOP
from ..log import logger
from .check import chromium_preflight_check

try:
    from playwright.async_api import Browser, Page, async_playwright
except Exception:
    logger.info("[AIRI] Installing Chromium for Playwright...")
    import subprocess

    subprocess.run(["playwright", "install", "chromium"], check=True)
    from playwright.async_api import Browser, Page, async_playwright

T = TypeVar("T")


def is_airi_repo(p: Path) -> bool:
    if not p:
        return False
    p = p.resolve()
    return (p / "package.json").exists() and (p / "pnpm-lock.yaml").exists()


env_val = os.getenv("AIRI_REPO_DIR", "").strip()
AIRI_REPO_DIR = Path(env_val) if env_val else None
if not AIRI_REPO_DIR or env_val in {".", "./"} or not is_airi_repo(AIRI_REPO_DIR):
    AIRI_REPO_DIR = Path(__file__).resolve().parents[4] / "third_party" / "airi"
AIRI_PORT: int = 5173


class AiriRunner(_InferenceRunner):
    INFERENCE_METHOD = "alphaavatar_character_airi"

    def __init__(self) -> None:
        super().__init__()
        self._repo_dir = AIRI_REPO_DIR
        self._port = AIRI_PORT
        self._proc: asyncio.subprocess.Process | None = None

        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None

    def _ensure_loop(self) -> None:
        if self._loop and not self._loop.is_closed():
            return

        loop = asyncio.new_event_loop()
        self._loop = loop

        def _run_loop():
            asyncio.set_event_loop(loop)
            loop.run_forever()

        self._loop_thread = threading.Thread(target=_run_loop, daemon=True)
        self._loop_thread.start()

    def _submit_coro(self, coro: Coroutine[Any, Any, T]) -> Future[T]:
        self._ensure_loop()
        assert self._loop is not None
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

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
                if self._proc is not None and self._proc.returncode is not None:
                    raise RuntimeError(
                        f"AIRI dev server process exited early (code={self._proc.returncode})."
                    )

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

    async def _start_server(self) -> None:
        stage_web_dir = self._repo_dir / "apps" / "stage-web"

        env = os.environ.copy()

        self._proc = await asyncio.create_subprocess_exec(
            "pnpm",
            "dev",
            "--host",
            "127.0.0.1",
            "--port",
            str(self._port),
            cwd=str(stage_web_dir),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        asyncio.create_task(self._log_output())

        await self._wait_for_server_ready()

    async def _run_headless_browser(
        self, livekit_url: str, livekit_token: str, agent_identity: str
    ):
        await chromium_preflight_check(timeout_s=10.0)
        await self._wait_for_server_ready(timeout=30.0)

        browser: Browser | None = None
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--autoplay-policy=no-user-gesture-required",
                        "--use-fake-ui-for-media-stream",
                        "--use-fake-device-for-media-stream",
                        "--mute-audio",
                        "--no-sandbox",
                    ],
                )
                page: Page = await browser.new_page()

                page.on("console", lambda msg: logger.info(f"[console] {msg.type}: {msg.text}"))
                page.on("pageerror", lambda exc: logger.error(f"[pageerror] {exc}"))
                page.on(
                    "requestfailed",
                    lambda req: logger.warning(
                        f"[requestfailed] {req.method} {req.url} -> {req.failure}"
                    ),
                )

                query = urllib.parse.urlencode(
                    {
                        "livekitUrl": livekit_url,
                        "livekitToken": livekit_token,
                        "agentIdentity": agent_identity,
                    }
                )
                url = f"http://127.0.0.1:{self._port}/livekit-avatar?{query}"

                logger.info(f"[AIRI] Opening headless page: {url}")
                await page.goto(url, wait_until="domcontentloaded", timeout=60_000)

                while True:
                    await asyncio.sleep(3600)

        except asyncio.CancelledError:
            logger.info("[AIRI] Headless browser task cancelled")
            raise
        except Exception:
            logger.exception("[AIRI] Headless browser task crashed")
        finally:
            try:
                if browser:
                    await browser.close()
            except Exception:
                pass
            logger.info("[AIRI] Headless browser task finished")

    def _run_livekit_avatar(
        self,
        livekit_url: str,
        livekit_token: str,
        agent_identity: str,
    ) -> None:
        if self._proc is None or self._proc.returncode is not None:
            raise RuntimeError("AIRI dev server is not running. Did you call initialize()?")

        logger.info("[AIRI] starting headless browser for LiveKit avatar")
        self._submit_coro(
            self._run_headless_browser(
                livekit_url=livekit_url,
                livekit_token=livekit_token,
                agent_identity=agent_identity,
            )
        )

    def initialize(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            return

        fut = self._submit_coro(self._start_server())
        fut.result(timeout=180)

    def run(self, data: bytes) -> bytes | None:
        json_data = json.loads(data)

        match json_data["op"]:
            case RunnerOP.run:
                self._run_livekit_avatar(**json_data["param"])
                return None
            case _:
                return None
