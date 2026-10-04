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

from alphaavatar.agents.avatar.provider.errors import ModelProtocolError
from alphaavatar.agents.avatar.provider.schemas import ProviderUsage


def normalize_usage(raw: dict[str, Any] | None) -> ProviderUsage | None:
    if raw is None:
        return None

    def count(value: Any) -> int | None:
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise ModelProtocolError("Invalid Responses token accounting")
        return value

    input_tokens = count(raw.get("input_tokens"))
    cached = count((raw.get("input_tokens_details") or {}).get("cached_tokens"))
    if input_tokens is not None and cached is not None and cached > input_tokens:
        raise ModelProtocolError("Cached input tokens exceed total input tokens")
    return ProviderUsage(
        input_tokens=input_tokens,
        output_tokens=count(raw.get("output_tokens")),
        total_tokens=count(raw.get("total_tokens")),
        cache_read_input_tokens=cached,
        cached_input_tokens=cached,
        uncached_input_tokens=(
            input_tokens - cached if input_tokens is not None and cached is not None else None
        ),
        reasoning_output_tokens=count(
            (raw.get("output_tokens_details") or {}).get("reasoning_tokens")
        ),
        raw=dict(raw),
    )
