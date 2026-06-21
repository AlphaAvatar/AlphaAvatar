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

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from alphaavatar.agents.providers.schema import ProviderUsage


def to_plain_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}

    if isinstance(value, dict):
        return value

    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")

    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except Exception:
            pass

    if hasattr(value, "dict"):
        try:
            return value.dict()
        except Exception:
            pass

    return {}


def get_attr_or_key(value: Any, key: str, default: Any = None) -> Any:
    if value is None:
        return default

    if isinstance(value, dict):
        return value.get(key, default)

    return getattr(value, key, default)


def get_nested(data: Any, *path: str, default: Any = None) -> Any:
    current = data

    for key in path:
        if current is None:
            return default

        if isinstance(current, dict):
            current = current.get(key)
        else:
            current = getattr(current, key, None)

    return current if current is not None else default


def to_int(value: Any) -> int | None:
    if value is None:
        return None

    try:
        return int(value)
    except Exception:
        return None


def to_float(value: Any) -> float | None:
    if value is None:
        return None

    try:
        return float(value)
    except Exception:
        return None


def sum_optional(*values: int | None) -> int | None:
    real_values = [v for v in values if v is not None]

    if not real_values:
        return None

    return sum(real_values)


def calculate_total_tokens(
    *,
    input_tokens: int | None,
    output_tokens: int | None,
    total_tokens: int | None = None,
) -> int | None:
    if total_tokens is not None:
        return total_tokens

    return sum_optional(input_tokens, output_tokens)


def calculate_cached_input_tokens(
    *,
    cache_read_input_tokens: int | None,
    cache_write_input_tokens: int | None,
    cached_input_tokens: int | None = None,
) -> int | None:
    if cached_input_tokens is not None:
        return cached_input_tokens

    return sum_optional(cache_read_input_tokens, cache_write_input_tokens)


def calculate_uncached_input_tokens(
    *,
    input_tokens: int | None,
    cached_input_tokens: int | None,
    uncached_input_tokens: int | None = None,
) -> int | None:
    if uncached_input_tokens is not None:
        return uncached_input_tokens

    if input_tokens is None or cached_input_tokens is None:
        return None

    return max(input_tokens - cached_input_tokens, 0)


def extract_langchain_raw_response(raw_response: Any) -> Any:
    """
    Supports both:
    - AIMessage returned directly by LangChain
    - dict returned by with_structured_output(..., include_raw=True)
      e.g. {"raw": AIMessage, "parsed": ..., "parsing_error": None}
    """
    if isinstance(raw_response, dict) and "raw" in raw_response:
        return raw_response.get("raw")

    return raw_response


def extract_langchain_usage_metadata(raw_response: Any) -> dict[str, Any]:
    raw = extract_langchain_raw_response(raw_response)
    usage_metadata = get_attr_or_key(raw, "usage_metadata", None)

    return to_plain_dict(usage_metadata)


def extract_langchain_response_metadata(raw_response: Any) -> dict[str, Any]:
    raw = extract_langchain_raw_response(raw_response)
    response_metadata = get_attr_or_key(raw, "response_metadata", None)

    return to_plain_dict(response_metadata)


class UsageNormalizer(ABC):
    @abstractmethod
    def normalize(
        self,
        *,
        raw_response: Any = None,
        raw_usage: dict[str, Any] | None = None,
    ) -> ProviderUsage: ...
