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
import pathlib
from typing import Any

from pydantic import BaseModel

from alphaavatar.agents.log import logger
from alphaavatar.agents.providers.schema import ProviderTraceConfig, ProviderTraceRecord
from alphaavatar.agents.utils import local_now_iso, short_hash

PROVIDER_TASKS_DIR = "tasks"
PROVIDER_TRACE_FILE = "traces.jsonl"
PROVIDER_PROMPT_DIR = "prompts"
PROVIDER_RAW_RESPONSE_DIR = "raw_responses"


def safe_task_dir_name(task_name: str) -> str:
    """
    Keep task names readable while avoiding path separators.
    Examples:
    - memory.conversation_delta -> memory.conversation_delta
    - memory/conversation_delta -> memory_conversation_delta
    """
    return task_name.strip().replace("/", "_").replace("\\", "_").replace(" ", "_")


def to_jsonable(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")

    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}

    if isinstance(value, list | tuple | set):
        return [to_jsonable(v) for v in value]

    if isinstance(value, str | int | float | bool):
        return value

    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except Exception as e:
            logger.exception("Error occurred while converting value to JSON", exc_info=e)
            pass

    if hasattr(value, "dict"):
        try:
            return value.dict()
        except Exception as e:
            logger.exception("Error occurred while converting value to JSON", exc_info=e)
            pass

    return str(value)


def safe_json_dumps(value: Any) -> str:
    return json.dumps(to_jsonable(value), ensure_ascii=False, sort_keys=True, default=str)


def get_provider_dir_from_metadata(metadata: dict[str, Any] | None) -> pathlib.Path | None:
    if not metadata:
        return None

    provider_dir = metadata.get("provider_dir")
    if provider_dir:
        return pathlib.Path(provider_dir)

    return None


class ProviderTracer:
    def __init__(self, config: ProviderTraceConfig | None = None) -> None:
        self._config = config or ProviderTraceConfig()

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    @property
    def save_prompt(self) -> bool:
        return self._config.save_prompt

    @property
    def save_raw_response(self) -> bool:
        return self._config.save_raw_response

    def build_trace_id(self, *, task_name: str, input_hash: str) -> str:
        seed = f"{task_name}:{input_hash}:{local_now_iso()}"
        return f"ptrace_{short_hash(seed, 20)}"

    def get_task_dir(
        self,
        *,
        task_name: str,
        metadata: dict[str, Any] | None = None,
    ) -> pathlib.Path:
        task_dir_name = safe_task_dir_name(task_name)

        path = (
            get_provider_dir_from_metadata(metadata=metadata) / PROVIDER_TASKS_DIR / task_dir_name
        )

        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_trace_file(
        self,
        *,
        task_name: str,
        metadata: dict[str, Any] | None = None,
    ) -> pathlib.Path:
        return (
            self.get_task_dir(
                task_name=task_name,
                metadata=metadata,
            )
            / PROVIDER_TRACE_FILE
        )

    def get_prompt_dir(
        self,
        *,
        task_name: str,
        metadata: dict[str, Any] | None = None,
    ) -> pathlib.Path:
        path = self.get_task_dir(task_name=task_name, metadata=metadata) / PROVIDER_PROMPT_DIR
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_raw_response_dir(
        self,
        *,
        task_name: str,
        metadata: dict[str, Any] | None = None,
    ) -> pathlib.Path:
        path = self.get_task_dir(task_name=task_name, metadata=metadata) / PROVIDER_RAW_RESPONSE_DIR
        path.mkdir(parents=True, exist_ok=True)
        return path

    def emit_record(self, record: ProviderTraceRecord) -> None:
        if not self.enabled:
            return

        self._emit(lambda: self._safe_write_record(record))

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

        self._emit(
            lambda: self._safe_write_prompt(
                trace_id=trace_id,
                task_name=task_name,
                prompt=prompt,
                payload=payload,
                metadata=metadata,
            )
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

        self._emit(
            lambda: self._safe_write_raw_response(
                trace_id=trace_id,
                task_name=task_name,
                raw_response=raw_response,
                metadata=metadata,
            )
        )

    def _emit(self, fn) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(asyncio.to_thread(fn))
        except RuntimeError:
            # No running event loop, fallback to sync.
            fn()
        except Exception as e:
            logger.error("Error occurred while emitting trace event", exc_info=e)

    def _safe_write_record(self, record: ProviderTraceRecord) -> None:
        try:
            self.write_record(record)
        except Exception as e:
            logger.error("Error occurred while writing trace record", exc_info=e)

    def _safe_write_prompt(
        self,
        *,
        trace_id: str,
        task_name: str,
        prompt: Any,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            self.write_prompt(
                trace_id=trace_id,
                task_name=task_name,
                prompt=prompt,
                payload=payload,
                metadata=metadata,
            )
        except Exception as e:
            logger.error("Error occurred while writing trace prompt", exc_info=e)

    def _safe_write_raw_response(
        self,
        *,
        trace_id: str,
        task_name: str,
        raw_response: Any,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            self.write_raw_response(
                trace_id=trace_id,
                task_name=task_name,
                raw_response=raw_response,
                metadata=metadata,
            )
        except Exception as e:
            logger.exception("Error occurred while writing raw response", exc_info=e)

    def write_record(self, record: ProviderTraceRecord) -> None:
        metadata = record.metadata or {}
        path = self.get_trace_file(
            task_name=record.task_name,
            metadata=metadata,
        )

        with path.open("a", encoding="utf-8") as f:
            f.write(safe_json_dumps(record))
            f.write("\n")

    def write_prompt(
        self,
        *,
        trace_id: str,
        task_name: str,
        prompt: Any,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        prompt_payload = {
            "trace_id": trace_id,
            "task_name": task_name,
            "prompt": to_jsonable(prompt),
            "payload": to_jsonable(payload),
            "metadata": to_jsonable(metadata or {}),
            "created_at": local_now_iso(),
        }

        serialized = safe_json_dumps(prompt_payload)

        path = (
            self.get_prompt_dir(
                task_name=task_name,
                metadata=metadata,
            )
            / f"{trace_id}.json"
        )

        path.write_text(serialized, encoding="utf-8")

    def write_raw_response(
        self,
        *,
        trace_id: str,
        task_name: str,
        raw_response: Any,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        serialized = safe_json_dumps(
            {
                "trace_id": trace_id,
                "task_name": task_name,
                "raw_response": to_jsonable(raw_response),
                "metadata": to_jsonable(metadata or {}),
            }
        )

        path = (
            self.get_raw_response_dir(
                task_name=task_name,
                metadata=metadata,
            )
            / f"{trace_id}.json"
        )

        path.write_text(serialized, encoding="utf-8")
