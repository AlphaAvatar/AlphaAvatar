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

from alphaavatar.agents.providers.enum import ProviderKind


class ProviderTaskConfig(BaseModel):
    kind: ProviderKind = ProviderKind.LLM

    provider: str = "openai"
    model: str

    temperature: float = 0.1
    timeout: float = 30.0

    prompt_version: str | None = None

    # Provider-specific kwargs, such as:
    # - base_url
    # - max_tokens
    # - media_resolution
    # - reasoning_effort
    # - fallback models
    extra: dict[str, Any] = Field(default_factory=dict)


class ProviderTraceConfig(BaseModel):
    enabled: bool = True
    save_prompt: bool = True
    save_raw_response: bool = False


class ProvidersConfig(BaseModel):
    trace: ProviderTraceConfig = Field(default_factory=ProviderTraceConfig)
    tasks: dict[str, ProviderTaskConfig] = Field(default_factory=dict)
