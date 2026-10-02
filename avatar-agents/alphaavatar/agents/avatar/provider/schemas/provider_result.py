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
from typing import Any

from pydantic import BaseModel, Field

from .usage import ProviderUsage


class ProviderResult(BaseModel):
    task_name: str

    provider: str
    model: str

    output: Any = None

    trace_id: str
    generation_id: str | None = None

    latency_ms: float | None = None
    usage: ProviderUsage | None = None

    prompt_hash: str | None = None
    prompt_version: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)
    raw_response: dict[str, Any] | None = None
