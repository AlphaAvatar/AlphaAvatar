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
import time
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from alphaavatar.agents.utils import sha256_text

from .base import LLMBase
from .registry import ProviderRegistry
from .schemas import ProviderResult, ProvidersConfig, ProviderTraceRecord
from .schemas.prompt import ModelPrompt
from .trace import ProviderTracer, safe_json_dumps, to_jsonable

if TYPE_CHECKING:
    from alphaavatar.agents.runtime.modules.foundation import ProviderService


class ProviderGateway:
    def __init__(self, config: ProvidersConfig, *, service: ProviderService) -> None:
        self._registry = ProviderRegistry(config)
        self._service = service
        self._tracer = service.tracer(self._registry.config.trace)

    @property
    def registry(self) -> ProviderRegistry:
        return self._registry

    @property
    def tracer(self) -> ProviderTracer:
        return self._tracer

    def _model(self, task_name: str) -> LLMBase:
        return self._service.model(self._registry.get_task_config(task_name))

    def validate_tasks(
        self, task_names: Iterable[str], *, require_input_adapter: bool = False
    ) -> None:
        task_names = tuple(task_names)
        self._registry.validate_tasks(task_names)
        for task_name in task_names:
            self._model(task_name).validate_input(require_input_adapter=require_input_adapter)

    async def ainvoke_structured(
        self,
        *,
        task_name: str,
        prompt: ModelPrompt,
        payload: dict[str, Any],
        output_schema: type[BaseModel],
        metadata: dict[str, Any] | None = None,
        tracing_payload: bool = True,
    ) -> ProviderResult:
        return await self._service.run(
            lambda: self._invoke_structured(
                task_name=task_name,
                prompt=prompt,
                payload=payload,
                output_schema=output_schema,
                metadata=metadata,
                tracing_payload=tracing_payload,
            )
        )

    async def _invoke_structured(
        self,
        *,
        task_name: str,
        prompt: ModelPrompt,
        payload: dict[str, Any],
        output_schema: type[BaseModel],
        metadata: dict[str, Any] | None = None,
        tracing_payload: bool = True,
    ) -> ProviderResult:
        if not isinstance(prompt, ModelPrompt):
            raise TypeError("ProviderGateway requires an AlphaAvatar ModelPrompt")
        if not isinstance(output_schema, type) or not issubclass(output_schema, BaseModel):
            raise TypeError("output_schema must be a Pydantic model class")

        metadata = dict(metadata or {})
        task_name = str(task_name)
        config = self._registry.get_task_config(task_name)
        input_blob = {
            "task_name": task_name,
            "backend": config.backend,
            "provider": config.provider,
            "model": config.model,
            "prompt": to_jsonable(prompt),
            "payload": to_jsonable(payload) if tracing_payload else {},
            "metadata": to_jsonable(metadata),
        }

        input_hash = sha256_text(safe_json_dumps(input_blob))
        prompt_hash = sha256_text(
            safe_json_dumps({"prompt": prompt, "prompt_version": config.prompt_version})
        )
        trace_id = self._tracer.build_trace_id(task_name=task_name, input_hash=input_hash)
        self._tracer.emit_prompt(
            trace_id=trace_id,
            task_name=task_name,
            prompt=prompt,
            payload=payload if tracing_payload else {},
            metadata=metadata,
        )

        started_at = time.perf_counter()
        trace_fields = {
            "trace_id": trace_id,
            "task_name": task_name,
            "provider": config.provider,
            "model": config.model,
            "prompt_hash": prompt_hash,
            "input_hash": input_hash,
            "prompt_version": config.prompt_version,
            "metadata": metadata,
        }
        try:
            reply = await self._model(task_name).ainvoke_structured(
                prompt.render(payload),
                output_schema=output_schema,
                include_raw=self._tracer.save_raw_response,
            )
            if not isinstance(reply.output, output_schema):
                raise TypeError("Provider backend returned an unvalidated structured result")
            latency_ms = (time.perf_counter() - started_at) * 1000

            result = ProviderResult(
                task_name=task_name,
                provider=config.provider,
                model=config.model,
                output=reply.output,
                trace_id=trace_id,
                generation_id=reply.generation_id,
                latency_ms=latency_ms,
                usage=reply.usage,
                prompt_hash=prompt_hash,
                prompt_version=config.prompt_version,
                metadata=metadata,
                raw_response=reply.raw_response,
            )
            self._tracer.emit_record(
                ProviderTraceRecord(
                    **trace_fields,
                    status="success",
                    latency_ms=latency_ms,
                    usage=reply.usage,
                    output_hash=sha256_text(safe_json_dumps(reply.output)),
                    generation_id=reply.generation_id,
                )
            )
            self._tracer.emit_raw_response(
                trace_id=trace_id,
                task_name=task_name,
                raw_response=reply.raw_response,
                metadata=metadata,
            )

            return result
        except asyncio.CancelledError:
            self._tracer.emit_record(
                ProviderTraceRecord(
                    **trace_fields,
                    status="cancelled",
                    latency_ms=(time.perf_counter() - started_at) * 1000,
                )
            )
            raise
        except Exception as exc:
            self._tracer.emit_record(
                ProviderTraceRecord(
                    **trace_fields,
                    status="failed",
                    latency_ms=(time.perf_counter() - started_at) * 1000,
                    error=repr(exc),
                )
            )
            raise
