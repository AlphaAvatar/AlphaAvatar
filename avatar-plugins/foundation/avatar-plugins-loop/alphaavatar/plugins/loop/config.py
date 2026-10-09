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
from pydantic import BaseModel, ConfigDict, Field

from alphaavatar.agents.avatar.provider.schemas import ProviderTaskConfig, ProviderTraceConfig


class ToolPolicy(BaseModel):
    """Host-supplied execution facts, never inferred from a model's tool arguments."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    read_only: bool = False
    parallel_safe: bool = False
    approval_required: bool = True


class RealtimeLoopConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # model configuration
    model: ProviderTaskConfig
    trace: ProviderTraceConfig = Field(default_factory=ProviderTraceConfig)
    supported_reasoning_efforts: tuple[str, ...] = ()

    # policy configuration
    tool_policies: dict[str, ToolPolicy] = Field(default_factory=dict)
    feedback_timeout: float = Field(default=2.0, gt=0, allow_inf_nan=False)
    max_retiring_runs: int = Field(default=4, ge=0, le=32)
