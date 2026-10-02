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

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from .usage import ProviderUsage


@dataclass(frozen=True, slots=True)
class ProviderModelResult:
    """A validated structured value plus provider-neutral response facts."""

    output: BaseModel
    usage: ProviderUsage | None = None
    generation_id: str | None = None
    raw_response: dict[str, Any] | None = None
