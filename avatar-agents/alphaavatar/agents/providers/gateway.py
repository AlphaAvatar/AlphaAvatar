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

import time
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel

from alphaavatar.agents.utils import sha256_text

from .input_adapters import ProviderInputAdapterRegistry
from .llm import create_llm_model
from .registry import ProviderRegistry
from .schema import (
    ModelInput,
    ProviderResult,
    ProvidersConfig,
    ProviderTaskConfig,
    ProviderTraceRecord,
)
from .trace import (
    ProviderTracer,
    safe_json_dumps,
    to_jsonable,
)
from .usage import normalize_usage


class ProviderGateway:
    def __init__(self, config: ProvidersConfig | None = None) -> None:
        self._registry = ProviderRegistry(config)
        self._tracer = ProviderTracer(self._registry.config.trace)
        self._input_adapters = ProviderInputAdapterRegistry()

    @property
    def registry(self) -> ProviderRegistry:
        return self._registry

    @property
    def tracer(self) -> ProviderTracer:
        return self._tracer

    """Input Helper"""

    async def _adapt_payload(
        self,
        *,
        task_config: ProviderTaskConfig,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        model_inputs = {
            key: value for key, value in payload.items() if isinstance(value, ModelInput)
        }

        if not model_inputs:
            return payload

        if not task_config.input_adapter:
            raise ValueError(
                "Provider task received ModelInput but has no input_adapter: "
                f"provider={task_config.provider!r}, model={task_config.model!r}"
            )

        adapter = self._input_adapters.resolve(task_config.input_adapter)
        adapted = dict(payload)

        for key, model_input in model_inputs.items():
            adapted[key] = await adapter.adapt(
                model_input,
                config=task_config,
            )

        return adapted

    """Output Helper"""

    def _with_structured_output(
        self,
        *,
        llm: Any,
        output_schema: type[BaseModel],
        include_raw: bool,
    ) -> Any:
        """
        Prefer include_raw=True so we can keep provider usage metadata.
        Some wrappers may not support include_raw; fallback gracefully.
        """
        try:
            return llm.with_structured_output(output_schema, include_raw=include_raw)
        except TypeError:
            return llm.with_structured_output(output_schema)

    def _extract_parsed_output(self, raw_result: Any) -> Any:
        """
        LangChain with_structured_output(include_raw=True) usually returns:
        {
            "raw": AIMessage,
            "parsed": PydanticModel,
            "parsing_error": None
        }

        Without include_raw, it may return the parsed Pydantic object directly.
        """
        if isinstance(raw_result, dict) and "parsed" in raw_result:
            parsed = raw_result.get("parsed")
            parsing_error = raw_result.get("parsing_error")

            if parsed is None and parsing_error is not None:
                raise ValueError(f"Structured output parsing failed: {parsing_error}")

            return parsed

        return raw_result

    def _extract_raw_response(self, raw_result: Any) -> Any:
        if isinstance(raw_result, dict) and "raw" in raw_result:
            return raw_result.get("raw")

        return raw_result

    def _extract_generation_id(self, raw_result: Any) -> str | None:
        raw_response = self._extract_raw_response(raw_result)

        response_metadata = getattr(raw_response, "response_metadata", None)
        if isinstance(response_metadata, dict):
            for key in ["id", "generation_id", "response_id"]:
                value = response_metadata.get(key)
                if value:
                    return str(value)

        additional_kwargs = getattr(raw_response, "additional_kwargs", None)
        if isinstance(additional_kwargs, dict):
            for key in ["id", "generation_id", "response_id"]:
                value = additional_kwargs.get(key)
                if value:
                    return str(value)

        return None

    """API"""

    def validate_tasks(self, task_names: Iterable[str]) -> None:
        self._registry.validate_tasks(task_names)

    async def ainvoke_structured(
        self,
        *,
        task_name: str,
        prompt: Any,
        payload: dict[str, Any],
        output_schema: type[BaseModel],
        metadata: dict[str, Any] | None = None,
        tracing_payload: bool = True,
    ) -> ProviderResult:
        """
        Invoke a task-level LLM with structured output.

        prompt:
            Usually a LangChain ChatPromptTemplate.

        payload:
            Variables passed to the prompt.

        output_schema:
            Pydantic output output_schema.

        metadata:
            AlphaAvatar-side metadata:
            plugin/session/avatar/user/memory_type/etc.
        """
        metadata = metadata or {}
        task_name = str(task_name)
        task_config = self._registry.get_task_config(task_name)

        input_blob = {
            "task_name": task_name,
            "provider": task_config.provider,
            "model": task_config.model,
            "prompt": to_jsonable(prompt),
            "payload": to_jsonable(payload) if tracing_payload else {},
            "metadata": to_jsonable(metadata),
        }

        input_hash = sha256_text(safe_json_dumps(input_blob))
        prompt_hash = sha256_text(
            safe_json_dumps(
                {
                    "prompt": to_jsonable(prompt),
                    "prompt_version": task_config.prompt_version,
                }
            )
        )

        trace_id = self._tracer.build_trace_id(
            task_name=task_name,
            input_hash=input_hash,
        )

        self._tracer.emit_prompt(
            trace_id=trace_id,
            task_name=task_name,
            prompt=prompt,
            payload=payload if tracing_payload else {},
            metadata=metadata,
        )

        started_at = time.perf_counter()

        try:
            llm = create_llm_model(task_config)

            structured_llm = self._with_structured_output(
                llm=llm,
                output_schema=output_schema,
                include_raw=True,
            )

            chain = prompt | structured_llm

            adapted_payload = await self._adapt_payload(
                task_config=task_config,
                payload=payload,
            )
            raw_result = await chain.ainvoke(adapted_payload)

            latency_ms = (time.perf_counter() - started_at) * 1000

            parsed_output = self._extract_parsed_output(raw_result)
            raw_response = self._extract_raw_response(raw_result)

            usage = normalize_usage(
                provider=task_config.provider,
                raw_response=raw_result,
            )

            generation_id = self._extract_generation_id(raw_result)

            result = ProviderResult(
                task_name=task_name,
                provider=task_config.provider,
                model=task_config.model,
                output=parsed_output,
                trace_id=trace_id,
                generation_id=generation_id,
                latency_ms=latency_ms,
                usage=usage,
                prompt_hash=prompt_hash,
                prompt_version=task_config.prompt_version,
                metadata=metadata,
                raw_response=(
                    to_jsonable(raw_response) if self._tracer.save_raw_response else None
                ),
            )

            record = ProviderTraceRecord(
                trace_id=trace_id,
                task_name=task_name,
                provider=task_config.provider,
                model=task_config.model,
                status="success",
                latency_ms=latency_ms,
                usage=usage,
                prompt_hash=prompt_hash,
                input_hash=input_hash,
                output_hash=sha256_text(safe_json_dumps(parsed_output)),
                prompt_version=task_config.prompt_version,
                generation_id=generation_id,
                metadata=metadata,
            )

            self._tracer.emit_record(record)
            self._tracer.emit_raw_response(
                trace_id=trace_id,
                task_name=task_name,
                raw_response=raw_response,
                metadata=metadata,
            )

            return result

        except Exception as e:
            latency_ms = (time.perf_counter() - started_at) * 1000

            record = ProviderTraceRecord(
                trace_id=trace_id,
                task_name=task_name,
                provider=task_config.provider,
                model=task_config.model,
                status="failed",
                latency_ms=latency_ms,
                prompt_hash=prompt_hash,
                input_hash=input_hash,
                prompt_version=task_config.prompt_version,
                error=repr(e),
                metadata=metadata,
            )

            self._tracer.emit_record(record)

            raise
