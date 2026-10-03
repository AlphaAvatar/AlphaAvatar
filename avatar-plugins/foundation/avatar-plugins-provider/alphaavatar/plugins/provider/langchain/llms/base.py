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
from typing import Any

from pydantic import BaseModel

from alphaavatar.agents.avatar.provider.base import LLMBase
from alphaavatar.agents.avatar.provider.schemas import ModelInput, ProviderTaskConfig
from alphaavatar.agents.avatar.provider.schemas.model_result import ProviderModelResult
from alphaavatar.agents.avatar.provider.trace import to_jsonable
from alphaavatar.core.cleanup import wait_for_cleanup

from ..adapters import LangChainInputAdapterRegistry
from ..resources import ModelResources
from ..usage import normalize_usage
from .models import create_llm_model


class LangChainLLM(LLMBase):
    def __init__(self, config: ProviderTaskConfig) -> None:
        self._config = config.model_copy(deep=True)
        self._config.provider = self._config.provider.strip().lower()
        self._adapters = LangChainInputAdapterRegistry()
        self._resources = ModelResources()
        self._init_task: asyncio.Task[Any] | None = None
        self._schema_tasks: dict[type[BaseModel], asyncio.Task[Any]] = {}
        self._close_task: asyncio.Task[None] | None = None

    @staticmethod
    def _generation_id(raw: Any) -> str | None:
        for name in ("response_metadata", "additional_kwargs"):
            metadata = getattr(raw, name, None)
            if isinstance(metadata, dict):
                for key in ("id", "generation_id", "response_id"):
                    if metadata.get(key):
                        return str(metadata[key])
        return None

    def validate_input(self, *, require_input_adapter: bool = False) -> None:
        self._ensure_open()
        config = self._config
        if config.provider not in {
            "openai",
            "openrouter",
            "google",
            "gemini",
            "google_genai",
            "anthropic",
            "claude",
        }:
            raise ValueError(f"Unsupported LLM provider: {config.provider!r}")
        if require_input_adapter and config.input_adapter is None:
            raise ValueError("A multimodal task requires an explicit input_adapter")
        name = config.input_adapter or "langchain_text"
        if name == "langchain_gemini" and config.provider not in {
            "google",
            "gemini",
            "google_genai",
        }:
            raise ValueError("langchain_gemini requires a Google provider")
        self._adapters.resolve(name)

    def _ensure_open(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("LangChain task model is closing or closed")

    async def _initialize(self) -> Any:
        try:
            return await asyncio.to_thread(create_llm_model, self._config, self._resources)
        except BaseException:
            await self._resources.aclose()
            raise

    async def _model(self) -> Any:
        self._ensure_open()
        if self._init_task is None:
            self._init_task = asyncio.create_task(self._initialize(), name="provider_model_init")
        model = await asyncio.shield(self._init_task)
        self._ensure_open()
        return model

    async def _close(self) -> None:
        # Initialization remains owned even if its first request was cancelled.
        if self._init_task is not None:
            await asyncio.gather(self._init_task, return_exceptions=True)
        await asyncio.gather(*self._schema_tasks.values(), return_exceptions=True)
        self._schema_tasks.clear()
        await self._resources.aclose()

    async def ainvoke_structured(
        self, model_input: ModelInput, *, output_schema: type[BaseModel], include_raw: bool = False
    ) -> ProviderModelResult:
        if not isinstance(output_schema, type) or not issubclass(output_schema, BaseModel):
            raise TypeError("output_schema must be a Pydantic model class")

        self.validate_input()

        adapter = self._adapters.resolve(self._config.input_adapter or "langchain_text")
        messages = await adapter.adapt(model_input, config=self._config)
        llm = await self._model()
        if output_schema not in self._schema_tasks:
            self._schema_tasks[output_schema] = asyncio.create_task(
                asyncio.to_thread(llm.with_structured_output, output_schema, include_raw=True),
                name="provider_structured_schema",
            )
        structured = await asyncio.shield(self._schema_tasks[output_schema])
        self._ensure_open()
        async with asyncio.timeout(self._config.timeout):
            result = await structured.ainvoke(messages)

        if not isinstance(result, dict) or not {"raw", "parsed", "parsing_error"} <= result.keys():
            raise TypeError("Structured backend must return parsed/raw/parsing_error fields")

        if (error := result["parsing_error"]) is not None:
            if isinstance(error, BaseException) and not isinstance(error, Exception):
                raise error
            if isinstance(error, Exception):
                raise ValueError("Provider structured output parsing failed") from error
            raise ValueError(f"Provider structured output parsing failed: {error}")

        parsed = result["parsed"]
        if parsed is None:
            raise ValueError("Provider returned no structured output")

        output = (
            parsed if isinstance(parsed, output_schema) else output_schema.model_validate(parsed)
        )
        raw = result.get("raw")
        raw_json = to_jsonable(raw) if include_raw else None
        if raw_json is not None and not isinstance(raw_json, dict):
            raw_json = {"value": raw_json}

        return ProviderModelResult(
            output=output,
            usage=normalize_usage(provider=self._config.provider, raw_response=result),
            generation_id=self._generation_id(raw),
            raw_response=raw_json,
        )

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="langchain_model_close")
        await wait_for_cleanup(self._close_task)
