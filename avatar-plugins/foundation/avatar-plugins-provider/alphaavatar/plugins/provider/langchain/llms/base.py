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

from typing import Any

from pydantic import BaseModel

from alphaavatar.agents.avatar.provider.base import LLMBase
from alphaavatar.agents.avatar.provider.schemas import ModelInput, ProviderTaskConfig
from alphaavatar.agents.avatar.provider.schemas.model_result import ProviderModelResult
from alphaavatar.agents.avatar.provider.trace import to_jsonable

from ..adapters import LangChainInputAdapterRegistry
from ..usage import normalize_usage
from .models import create_llm_model


class LangChainLLM(LLMBase):
    def __init__(self, config: ProviderTaskConfig) -> None:
        self._config = config.model_copy(deep=True)
        self._config.provider = self._config.provider.strip().lower()
        self._adapters = LangChainInputAdapterRegistry()

    def validate_input(self, *, require_input_adapter: bool = False) -> None:
        config = self._config
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

    @staticmethod
    def _generation_id(raw: Any) -> str | None:
        for name in ("response_metadata", "additional_kwargs"):
            metadata = getattr(raw, name, None)
            if isinstance(metadata, dict):
                for key in ("id", "generation_id", "response_id"):
                    if metadata.get(key):
                        return str(metadata[key])
        return None

    async def ainvoke_structured(
        self, model_input: ModelInput, *, output_schema: type[BaseModel], include_raw: bool = False
    ) -> ProviderModelResult:
        if not isinstance(output_schema, type) or not issubclass(output_schema, BaseModel):
            raise TypeError("output_schema must be a Pydantic model class")

        self.validate_input()

        adapter = self._adapters.resolve(self._config.input_adapter or "langchain_text")
        messages = await adapter.adapt(model_input, config=self._config)

        llm = create_llm_model(self._config)
        structured = llm.with_structured_output(output_schema, include_raw=True)

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
