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

from alphaavatar.agents.providers.schema import ProviderUsage

from .base import (
    UsageNormalizer,
    calculate_cached_input_tokens,
    calculate_total_tokens,
    calculate_uncached_input_tokens,
    extract_langchain_response_metadata,
    extract_langchain_usage_metadata,
    get_nested,
    to_float,
    to_int,
)


class OpenAIUsageNormalizer(UsageNormalizer):
    def normalize(
        self,
        *,
        raw_response: Any = None,
        raw_usage: dict[str, Any] | None = None,
    ) -> ProviderUsage:
        usage_metadata = extract_langchain_usage_metadata(raw_response)
        response_metadata = extract_langchain_response_metadata(raw_response)

        # Native OpenAI/OpenRouter style usage may appear here in LangChain.
        token_usage = raw_usage or response_metadata.get("token_usage") or {}

        input_tokens = to_int(usage_metadata.get("input_tokens")) or to_int(
            token_usage.get("prompt_tokens")
        )
        output_tokens = to_int(usage_metadata.get("output_tokens")) or to_int(
            token_usage.get("completion_tokens")
        )
        total_tokens = to_int(usage_metadata.get("total_tokens")) or to_int(
            token_usage.get("total_tokens")
        )

        # LangChain normalized details.
        input_token_details = usage_metadata.get("input_token_details") or {}
        output_token_details = usage_metadata.get("output_token_details") or {}

        # Native OpenAI details.
        prompt_token_details = token_usage.get("prompt_tokens_details") or {}
        completion_token_details = token_usage.get("completion_tokens_details") or {}

        cache_read_input_tokens = (
            to_int(input_token_details.get("cache_read"))
            or to_int(input_token_details.get("cached_tokens"))
            or to_int(prompt_token_details.get("cached_tokens"))
        )

        cache_write_input_tokens = (
            to_int(input_token_details.get("cache_creation"))
            or to_int(input_token_details.get("cache_write"))
            or to_int(prompt_token_details.get("cache_write_tokens"))
        )

        cached_input_tokens = calculate_cached_input_tokens(
            cache_read_input_tokens=cache_read_input_tokens,
            cache_write_input_tokens=cache_write_input_tokens,
        )

        uncached_input_tokens = calculate_uncached_input_tokens(
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
        )

        reasoning_output_tokens = to_int(output_token_details.get("reasoning")) or to_int(
            completion_token_details.get("reasoning_tokens")
        )

        # Some OpenRouter-compatible responses may include cost in metadata.
        cost_usd = (
            to_float(token_usage.get("cost"))
            or to_float(token_usage.get("cost_usd"))
            or to_float(get_nested(response_metadata, "usage", "cost"))
            or to_float(get_nested(response_metadata, "usage", "cost_usd"))
        )

        return ProviderUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=calculate_total_tokens(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
            ),
            cache_read_input_tokens=cache_read_input_tokens,
            cache_write_input_tokens=cache_write_input_tokens,
            cached_input_tokens=cached_input_tokens,
            uncached_input_tokens=uncached_input_tokens,
            reasoning_output_tokens=reasoning_output_tokens,
            cost_usd=cost_usd,
            raw={
                "usage_metadata": usage_metadata,
                "response_metadata": response_metadata,
                "token_usage": token_usage,
            },
        )
