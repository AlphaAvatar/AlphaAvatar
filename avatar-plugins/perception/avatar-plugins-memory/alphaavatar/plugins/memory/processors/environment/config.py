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
from pydantic import BaseModel, ConfigDict, Field, model_validator

from alphaavatar.agents.avatar.provider.schemas import ProvidersConfig


class EnvironmentProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str | None = None
    gateway: ProvidersConfig = Field(default_factory=ProvidersConfig)


class EnvironmentSchedulerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    max_pending_batches: int = Field(default=2, ge=1, le=16)
    max_batch_events: int = Field(default=2048, ge=1, le=65536)
    max_batch_payload_bytes: int = Field(default=64 * 1024 * 1024, ge=1)
    max_batch_duration_sec: float = Field(default=30.0, gt=0, le=300)
    max_context_messages: int = Field(default=64, ge=1, le=1024)
    max_context_chars: int = Field(default=8192, ge=1, le=131072)
    process_timeout_sec: float = Field(default=45.0, gt=0, le=300)
    max_attempts: int = Field(default=2, ge=1, le=8)
    shutdown_timeout_sec: float = Field(default=5.0, gt=0, le=60)


class EnvironmentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    include_audio: bool = True
    provider: EnvironmentProviderConfig = Field(default_factory=EnvironmentProviderConfig)
    scheduler: EnvironmentSchedulerConfig = Field(default_factory=EnvironmentSchedulerConfig)

    @model_validator(mode="after")
    def _validate_provider(self) -> "EnvironmentConfig":
        if self.enabled and not self.provider.task:
            raise ValueError("environment.provider.task is required when environment is enabled")
        return self
