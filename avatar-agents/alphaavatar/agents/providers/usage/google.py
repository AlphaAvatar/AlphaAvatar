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
    calculate_total_tokens,
    calculate_uncached_input_tokens,
    extract_langchain_response_metadata,
    extract_langchain_usage_metadata,
    get_nested,
    to_float,
    to_int,
)


class GoogleUsageNormalizer(UsageNormalizer):
    def normalize(
        self,
        *,
        raw_response: Any = None,
        raw_usage: dict[str, Any] | None = None,
    ) -> ProviderUsage:
        usage_metadata = extract_langchain_usage_metadata(raw_response)
        response_metadata = extract_langchain_response_metadata(raw_response)

        native_usage = (
            raw_usage
            or response_metadata.get("usage_metadata")
            or response_metadata.get("usage")
            or {}
        )

        input_tokens = (
            to_int(usage_metadata.get("input_tokens"))
            or to_int(native_usage.get("prompt_token_count"))
            or to_int(native_usage.get("promptTokenCount"))
        )

        output_tokens = (
            to_int(usage_metadata.get("output_tokens"))
            or to_int(native_usage.get("candidates_token_count"))
            or to_int(native_usage.get("candidatesTokenCount"))
        )

        total_tokens = (
            to_int(usage_metadata.get("total_tokens"))
            or to_int(native_usage.get("total_token_count"))
            or to_int(native_usage.get("totalTokenCount"))
        )

        cache_read_input_tokens = (
            to_int(get_nested(usage_metadata, "input_token_details", "cache_read"))
            or to_int(native_usage.get("cached_content_token_count"))
            or to_int(native_usage.get("cachedContentTokenCount"))
        )

        # Gemini usually exposes cached content read tokens, not cache creation tokens.
        cache_write_input_tokens = (
            to_int(get_nested(usage_metadata, "input_token_details", "cache_creation"))
            or to_int(native_usage.get("cache_write_token_count"))
            or to_int(native_usage.get("cacheWriteTokenCount"))
        )

        cached_input_tokens = None
        if cache_read_input_tokens is not None or cache_write_input_tokens is not None:
            cached_input_tokens = (cache_read_input_tokens or 0) + (cache_write_input_tokens or 0)

        uncached_input_tokens = calculate_uncached_input_tokens(
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
        )

        reasoning_output_tokens = (
            to_int(get_nested(usage_metadata, "output_token_details", "reasoning"))
            or to_int(native_usage.get("thoughts_token_count"))
            or to_int(native_usage.get("thoughtsTokenCount"))
        )

        cost_usd = (
            to_float(native_usage.get("cost"))
            or to_float(native_usage.get("cost_usd"))
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
                "native_usage": native_usage,
            },
        )
