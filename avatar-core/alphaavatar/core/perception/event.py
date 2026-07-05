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
from dataclasses import dataclass, field
from typing import Any

from alphaavatar.core.env import EnvObservation


@dataclass(slots=True)
class FrameEvent:
    frame_id: str
    timestamp: str
    source_id: str

    payload: Any | None = field(default=None, repr=False, compare=False)

    # Optional model-facing representation.
    # For LiveKit frames this can be JPEG bytes.
    rendered_payload: Any | None = field(default=None, repr=False, compare=False)
    rendered_mime_type: str | None = None

    path: str | None = None
    mime_type: str | None = "image/jpeg"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_observation(self) -> EnvObservation:
        metadata = dict(self.metadata)
        metadata.setdefault("frame_id", self.frame_id)

        return EnvObservation.video_frame(
            timestamp=self.timestamp,
            source_id=self.source_id,
            path=self.path,
            payload=self.payload,
            rendered_payload=self.rendered_payload,
            rendered_mime_type=self.rendered_mime_type,
            metadata=metadata,
        )
