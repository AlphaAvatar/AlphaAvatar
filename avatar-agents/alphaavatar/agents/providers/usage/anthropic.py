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


class AnthropicUsageNormalizer(UsageNormalizer):
    def normalize(
        self,
        *,
        raw_response: Any = None,
        raw_usage: dict[str, Any] | None = None,
    ) -> ProviderUsage:
        usage_metadata = extract_langchain_usage_metadata(raw_response)
        response_metadata = extract_langchain_response_metadata(raw_response)

        token_usage = raw_usage or response_metadata.get("usage") or {}

        # LangChain normalized fields.
        lc_input_tokens = to_int(usage_metadata.get("input_tokens"))
        lc_output_tokens = to_int(usage_metadata.get("output_tokens"))
        lc_total_tokens = to_int(usage_metadata.get("total_tokens"))

        # Anthropic native fields.
        native_uncached_input_tokens = to_int(token_usage.get("input_tokens"))
        native_output_tokens = to_int(token_usage.get("output_tokens"))
        cache_read_input_tokens = to_int(token_usage.get("cache_read_input_tokens"))
        cache_write_input_tokens = to_int(token_usage.get("cache_creation_input_tokens"))

        native_total_input_tokens = calculate_total_tokens(
            input_tokens=sum(
                v or 0
                for v in [
                    native_uncached_input_tokens,
                    cache_read_input_tokens,
                    cache_write_input_tokens,
                ]
            )
            if any(
                v is not None
                for v in [
                    native_uncached_input_tokens,
                    cache_read_input_tokens,
                    cache_write_input_tokens,
                ]
            )
            else None,
            output_tokens=None,
        )

        input_tokens = lc_input_tokens or native_total_input_tokens
        output_tokens = lc_output_tokens or native_output_tokens
        total_tokens = lc_total_tokens or calculate_total_tokens(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

        cached_input_tokens = calculate_cached_input_tokens(
            cache_read_input_tokens=cache_read_input_tokens,
            cache_write_input_tokens=cache_write_input_tokens,
        )

        uncached_input_tokens = calculate_uncached_input_tokens(
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            uncached_input_tokens=native_uncached_input_tokens,
        )

        reasoning_output_tokens = (
            to_int(get_nested(usage_metadata, "output_token_details", "reasoning"))
            or to_int(token_usage.get("reasoning_output_tokens"))
            or to_int(token_usage.get("thinking_tokens"))
        )

        cost_usd = (
            to_float(token_usage.get("cost"))
            or to_float(token_usage.get("cost_usd"))
            or to_float(get_nested(response_metadata, "usage", "cost"))
            or to_float(get_nested(response_metadata, "usage", "cost_usd"))
        )

        return ProviderUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
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
