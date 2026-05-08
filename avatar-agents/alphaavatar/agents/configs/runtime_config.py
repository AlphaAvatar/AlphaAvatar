# Copyright 2025 AlphaAvatar project
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
from pydantic import BaseModel, Field

from alphaavatar.agents.avatar.context.enum.injection_mode import RuntimeContextInjectionMode


class RuntimeConfig(BaseModel):
    """Dataclass which contains all runtime-related configuration, which will creat for each session."""

    runtime_context_mode: RuntimeContextInjectionMode = Field(
        default=RuntimeContextInjectionMode.USER_APPEND,
        description="How to inject dynamic runtime context into the model input.",
    )
