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

from alphaavatar.agents.providers import ProvidersConfig


class EnvironmentProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str | None = None
    gateway: ProvidersConfig = Field(default_factory=ProvidersConfig)


class EnvironmentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    include_audio: bool = True
    provider: EnvironmentProviderConfig = Field(default_factory=EnvironmentProviderConfig)

    @model_validator(mode="after")
    def _validate_provider(self) -> "EnvironmentConfig":
        if self.enabled and not self.provider.task:
            raise ValueError("environment.provider.task is required when environment is enabled")
        return self
