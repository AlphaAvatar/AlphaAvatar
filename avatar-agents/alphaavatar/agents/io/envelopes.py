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
from typing import Any, Literal

InputModality = Literal["text", "audio", "image", "video", "multimodal"]
OutputModality = Literal["text"]


@dataclass
class InputEnvelope:
    channel: str
    user_id: str
    session_id: str
    room_name: str
    message_id: str
    modality: InputModality

    text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OutputEnvelope:
    channel: str
    user_id: str
    session_id: str
    room_name: str
    correlation_id: str
    modality: OutputModality

    text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
