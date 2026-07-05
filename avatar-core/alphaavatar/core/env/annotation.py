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
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class EnvAnnotation:
    """
    Lightweight environment annotation attached to an observation or frame.

    Examples:
    - face boxes from persona.face_stream
    - object boxes from interaction_router
    - gaze/focus regions from avatar vision
    - OCR/screen regions
    - speaker/voice alignment metadata

    This object must stay LiveKit-independent.
    """

    source: str
    annotation_type: str
    data: dict[str, Any]

    # Usually one of these two is enough.
    frame_id: str | None = None
    observation_id: str | None = None

    timestamp: str | None = None
    annotation_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @property
    def target_key(self) -> str | None:
        if self.observation_id:
            return f"observation:{self.observation_id}"
        if self.frame_id:
            return f"frame:{self.frame_id}"
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "annotation_id": self.annotation_id,
            "source": self.source,
            "type": self.annotation_type,
            "timestamp": self.timestamp,
            "frame_id": self.frame_id,
            "observation_id": self.observation_id,
            "data": self.data,
        }
