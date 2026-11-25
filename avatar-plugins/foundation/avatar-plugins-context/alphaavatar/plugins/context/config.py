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
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from alphaavatar.agents.constants import DEFAULT_SYSTEM_VALUE

# Profiles `config init` wrote while the history had capacity limits; it is now kept whole.
_HISTORY_LIMITS = frozenset({"history_max_turns", "history_max_items", "history_max_bytes"})


class ContextConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    behavior_rules: str = DEFAULT_SYSTEM_VALUE
    max_pending_preparations: int = Field(default=16, ge=1, le=128)

    @model_validator(mode="before")
    @classmethod
    def _ignore_history_limits(cls, data: Any) -> Any:
        # Read and ignored; any other unknown setting is still refused.
        if isinstance(data, Mapping):
            return {key: value for key, value in data.items() if key not in _HISTORY_LIMITS}
        return data
