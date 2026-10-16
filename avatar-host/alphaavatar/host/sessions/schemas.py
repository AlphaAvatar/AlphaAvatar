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

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attachment_id: str = Field(min_length=1, max_length=256)
    backend: str = Field(min_length=1, max_length=64)
    source_id: str = Field(min_length=1, max_length=256)
    connection: dict[str, Any] = Field(repr=False)


@dataclass(frozen=True, slots=True)
class SessionContext:
    participant_identity: str
    agent_identity: str
    room_name: str
    metadata: dict[str, Any] = field(repr=False)
    room_type: str = "alphaavatar_app"


@dataclass(frozen=True, slots=True)
class SessionEnd:
    attachment_id: str
    reason: str
    failed: bool = False
