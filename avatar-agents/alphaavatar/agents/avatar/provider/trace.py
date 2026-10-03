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
import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from alphaavatar.agents.utils.time import application_now
from alphaavatar.core.cleanup import wait_for_cleanup

from .schemas import ProviderTraceConfig, ProviderTraceRecord

logger = logging.getLogger(__name__)

PROVIDER_TASKS_DIR = "tasks"
PROVIDER_TRACE_FILE = "traces.jsonl"
PROVIDER_PROMPT_DIR = "prompts"
PROVIDER_RAW_RESPONSE_DIR = "raw_responses"


def safe_task_dir_name(task_name: str) -> str:
    name = task_name.strip().replace("/", "_").replace("\\", "_").replace(" ", "_")
    if name in {"", ".", ".."}:
        raise ValueError("Provider trace task directory cannot be empty or a traversal component")
    return name


def to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [to_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    return str(value)


def safe_json_dumps(value: Any) -> str:
    return json.dumps(to_jsonable(value), ensure_ascii=False, sort_keys=True, default=str)


def get_provider_dir_from_metadata(metadata: dict[str, Any] | None) -> Path | None:
    value = (metadata or {}).get("provider_dir")
    return Path(value) if value else None


class ProviderTracer:
    """Best-effort bounded diagnostics; close drains every accepted write before returning."""

    def __init__(self, config: ProviderTraceConfig | None = None) -> None:
        self._config = (config or ProviderTraceConfig()).model_copy(deep=True)
        self._queue: asyncio.Queue[Callable[[], None] | None] = asyncio.Queue(
            maxsize=self._config.max_pending
        )
        self._worker: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._dropped_writes = 0
        self._failed_writes = 0
        self._skipped_writes = 0

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    @property
    def save_prompt(self) -> bool:
        return self._config.save_prompt

    @property
    def save_raw_response(self) -> bool:
        return self._config.save_raw_response

    @property
    def dropped_writes(self) -> int:
        return self._dropped_writes

    @property
    def failed_writes(self) -> int:
        return self._failed_writes

    @property
    def skipped_writes(self) -> int:
        return self._skipped_writes

    def build_trace_id(self, *, task_name: str, input_hash: str) -> str:
        return f"ptrace_{uuid4().hex}"

    def get_task_dir(self, *, task_name: str, metadata: dict[str, Any] | None = None) -> Path:
        root = get_provider_dir_from_metadata(metadata)
        if root is None:
            raise ValueError("Provider tracing requires provider_dir metadata")
        path = root / PROVIDER_TASKS_DIR / safe_task_dir_name(task_name)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _emit(self, write: Callable[[], None], metadata: dict[str, Any] | None) -> None:
        if not self.enabled:
            return
        if self._close_task is not None:
            raise RuntimeError("Provider tracer is closing or closed")
        if get_provider_dir_from_metadata(metadata) is None:
            self._skipped_writes += 1
            return
        loop = asyncio.get_running_loop()
        if self._worker is None:
            self._worker = loop.create_task(self._run(), name="provider_trace_writer")
        try:
            self._queue.put_nowait(write)
        except asyncio.QueueFull:
            self._dropped_writes += 1
            if self._dropped_writes == 1:
                logger.warning("Provider trace queue is full; diagnostic writes are being dropped")

    async def _run(self) -> None:
        while True:
            write = await self._queue.get()
            try:
                if write is None:
                    return
                try:
                    await asyncio.to_thread(write)
                except Exception:
                    self._failed_writes += 1
                    logger.exception("Provider trace write failed")
            finally:
                self._queue.task_done()

    def emit_record(self, record: ProviderTraceRecord) -> None:
        if self.enabled:
            record = record.model_copy(deep=True)
            self._emit(lambda: self.write_record(record), record.metadata)

    def emit_prompt(
        self,
        *,
        trace_id: str,
        task_name: str,
        prompt: Any,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled or not self.save_prompt:
            return
        payload, metadata = dict(payload), dict(metadata or {})
        self._emit(
            lambda: self.write_prompt(
                trace_id=trace_id,
                task_name=task_name,
                prompt=prompt,
                payload=payload,
                metadata=metadata,
            ),
            metadata,
        )

    def emit_raw_response(
        self,
        *,
        trace_id: str,
        task_name: str,
        raw_response: Any,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled or not self.save_raw_response:
            return
        metadata = dict(metadata or {})
        self._emit(
            lambda: self.write_raw_response(
                trace_id=trace_id, task_name=task_name, raw_response=raw_response, metadata=metadata
            ),
            metadata,
        )

    def write_record(self, record: ProviderTraceRecord) -> None:
        path = self.get_task_dir(task_name=record.task_name, metadata=record.metadata)
        with (path / PROVIDER_TRACE_FILE).open("a", encoding="utf-8") as file:
            file.write(safe_json_dumps(record) + "\n")

    def write_prompt(
        self,
        *,
        trace_id: str,
        task_name: str,
        prompt: Any,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        path = self.get_task_dir(task_name=task_name, metadata=metadata) / PROVIDER_PROMPT_DIR
        path.mkdir(parents=True, exist_ok=True)
        document = {
            "trace_id": trace_id,
            "task_name": task_name,
            "prompt": to_jsonable(prompt),
            "payload": to_jsonable(payload),
            "metadata": to_jsonable(metadata or {}),
            "created_at": application_now().isoformat(),
        }
        (path / f"{trace_id}.json").write_text(safe_json_dumps(document), encoding="utf-8")

    def write_raw_response(
        self,
        *,
        trace_id: str,
        task_name: str,
        raw_response: Any,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        path = self.get_task_dir(task_name=task_name, metadata=metadata) / PROVIDER_RAW_RESPONSE_DIR
        path.mkdir(parents=True, exist_ok=True)
        document = {
            "trace_id": trace_id,
            "task_name": task_name,
            "raw_response": to_jsonable(raw_response),
            "metadata": to_jsonable(metadata or {}),
        }
        (path / f"{trace_id}.json").write_text(safe_json_dumps(document), encoding="utf-8")

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="provider_trace_close")
        await wait_for_cleanup(self._close_task)

    async def _close(self) -> None:
        if self._worker is not None:
            await self._queue.put(None)
            await self._worker
        if self._dropped_writes:
            logger.warning("Provider trace dropped %s writes", self._dropped_writes)
        if self._failed_writes:
            raise RuntimeError(f"Provider tracing failed to persist {self._failed_writes} writes")
