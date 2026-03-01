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

from typing import Any, Literal

from pydantic import BaseModel, Field


class WAInboundEvent(BaseModel):
    v: int = 1
    channel: Literal["whatsapp"] = "whatsapp"
    direction: Literal["in"] = "in"

    from_: str = Field(alias="from")  # E164 or wa id
    chat_id: str
    message_id: str
    ts: int

    type: Literal["text"] = "text"
    text: str

    meta: dict[str, Any] = Field(default_factory=dict)


class WAOutboundEvent(BaseModel):
    v: int = 1
    channel: Literal["whatsapp"] = "whatsapp"
    direction: Literal["out"] = "out"

    to: str
    chat_id: str
    correlation_id: str | None = None

    type: Literal["text"] = "text"
    text: str

    meta: dict[str, Any] = Field(default_factory=dict)
