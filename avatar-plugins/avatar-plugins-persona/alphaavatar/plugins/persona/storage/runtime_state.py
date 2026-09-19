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
import json
import os
import re
from collections.abc import Callable
from functools import partial
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TypeVar

from alphaavatar.agents.persona.schemas import UserRuntimeState
from alphaavatar.agents.utils.files.work_dirs import UserPath

from ..log import logger

T = TypeVar("T")

_BEGIN = "<!-- alphaavatar_runtime_state_json:start -->"
_END = "<!-- alphaavatar_runtime_state_json:end -->"
_BLOCK_PATTERN = re.compile(re.escape(_BEGIN) + r".*?" + re.escape(_END), re.DOTALL)
_JSON_PATTERN = re.compile(
    re.escape(_BEGIN) + r"\s*```json\s*(.*?)\s*```\s*" + re.escape(_END), re.DOTALL
)


class RuntimeStateStore:
    """Local runtime-state persistence; locks are scoped to this store instance."""

    def __init__(self) -> None:
        self._locks: dict[Path, asyncio.Lock] = {}

    @staticmethod
    def _path(user_path: UserPath) -> Path:
        return user_path.runtime_dir / "runtime_state.md"

    async def _run_io(self, path: Path, operation: Callable[[], T]) -> T:
        async with self._locks.setdefault(path, asyncio.Lock()):
            task = asyncio.create_task(asyncio.to_thread(operation))
            cancelled: asyncio.CancelledError | None = None

            # A cancelled caller must not release the lock while its disk operation is still running.
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError as exc:
                    if cancelled is None:
                        cancelled = exc
                except Exception:
                    break

            if cancelled is not None:
                if not task.cancelled() and (error := task.exception()) is not None:
                    logger.error(
                        "Runtime-state I/O failed during cancellation: %s", error, exc_info=error
                    )
                raise cancelled

            return task.result()

    async def load(self, *, user_path: UserPath) -> UserRuntimeState | None:
        path = self._path(user_path)
        return await self._run_io(path, partial(self._load, path))

    async def save(
        self,
        *,
        user_path: UserPath,
        runtime_state: UserRuntimeState,
    ) -> Path:
        path = self._path(user_path)
        snapshot = runtime_state.model_copy(deep=True)
        return await self._run_io(path, partial(self._save, path, snapshot))

    @staticmethod
    def _read_text(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    @classmethod
    def _load(cls, path: Path) -> UserRuntimeState | None:
        match = _JSON_PATTERN.search(cls._read_text(path))
        if match is None:
            return None

        try:
            return UserRuntimeState.model_validate_json(match.group(1))
        except ValueError as exc:
            logger.warning("Runtime state load failed path=%s: %s", path, exc)
            return None

    @classmethod
    def _save(cls, path: Path, state: UserRuntimeState) -> Path:
        data = state.model_dump(mode="json", exclude_none=True)
        latest_block = (
            f"{_BEGIN}\n```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```\n{_END}"
        )

        session_id = state.current_session_id or ""
        login_time = state.current_login_at.isoformat() if state.current_login_at else ""
        history_item = (
            f"<!-- session_id:{session_id} -->\n"
            f"- login_time: {login_time}\n"
            f"  session_id: {session_id}\n"
            f"  room_type: {state.current_room_type or ''}\n"
            f"  timezone: {state.current_timezone or ''}\n"
            f"  login_count: {state.login_count}\n"
        )

        old_text = cls._read_text(path)
        if old_text:
            if _BLOCK_PATTERN.search(old_text):
                text = _BLOCK_PATTERN.sub(lambda _: latest_block, old_text, count=1)
            else:
                text = f"# Runtime State\n\n{latest_block}\n\n## Previous Content\n\n{old_text}"

            if "## Login History" not in text:
                text = text.rstrip() + "\n\n## Login History\n\n"

            if session_id and f"<!-- session_id:{session_id} -->" not in text:
                text = text.rstrip() + "\n\n" + history_item
        else:
            text = f"# Runtime State\n\n{latest_block}\n\n## Login History\n\n{history_item}"

        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None

        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
            ) as file:
                temporary_path = Path(file.name)
                file.write(text)
                file.flush()
                os.fsync(file.fileno())

            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

        return path
