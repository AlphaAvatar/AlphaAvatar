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
from pathlib import Path

from ..log import logger


class AiriProcess:
    def __init__(self, repo_dir: Path, port: int) -> None:
        self._repo_dir = repo_dir
        self._port = port
        self._proc: asyncio.subprocess.Process | None = None

    async def start(
        self,
        livekit_url: str,
        livekit_token: str,
        agent_identity: str,
        avatar_identity: str,
    ) -> None:
        """启动 AIRI 的前端 dev/server 进程"""

        if self._proc and self._proc.returncode is None:
            return

        env = os.environ.copy()
        env["AIRI_LIVEKIT_URL"] = livekit_url
        env["AIRI_LIVEKIT_TOKEN"] = livekit_token
        env["AIRI_AGENT_IDENTITY"] = agent_identity
        env["AIRI_AVATAR_IDENTITY"] = avatar_identity
        env["AIRI_PORT"] = str(self._port)

        # Here we'll use pnpm dev first, but you can also switch to pnpm build + node server.js
        self._proc = await asyncio.create_subprocess_exec(
            "pnpm",
            "dev",
            "--",
            "--port",
            str(self._port),
            cwd=str(self._repo_dir),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        # Simply log the data to the Python logger function
        asyncio.create_task(self._log_output())

    async def _log_output(self):
        assert self._proc and self._proc.stdout
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                break
            logger.info("[AIRI frontend]", line.decode().rstrip())

    async def stop(self):
        if not self._proc:
            return
        if self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                self._proc.kill()
        self._proc = None
