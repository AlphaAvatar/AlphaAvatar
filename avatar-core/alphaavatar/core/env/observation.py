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
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .annotation import EnvAnnotation

EnvAnnotationRenderer = Callable[["EnvObservation", EnvAnnotation], None]


@dataclass(slots=True)
class EnvObservation:
    """
    Runtime environment observation.

    payload:
        Heavy runtime-only multimodal payload, such as frame bytes, audio bytes,
        video clip bytes, provider content block, or LiveKit VideoFrame.
        It must never be persisted to memory/VDB/markdown.

    path:
        Optional persisted keyframe/keyclip evidence path.
        Only selected evidence should have path.
    """

    kind: str  # video_frame / video_clip / audio_segment / screen_frame
    timestamp: str
    source_id: str

    observation_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    path: str | None = None
    mime_type: str | None = None
    payload: Any | None = field(default=None, repr=False, compare=False)

    rendered_payload: Any | None = field(default=None, repr=False, compare=False)
    rendered_mime_type: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)
    annotations: list[EnvAnnotation] = field(default_factory=list)

    @property
    def frame_id(self) -> str | None:
        value = self.metadata.get("frame_id")
        return str(value) if value else None

    @property
    def has_payload(self) -> bool:
        return self.payload is not None or self.rendered_payload is not None

    @property
    def has_persisted_evidence(self) -> bool:
        return bool(self.path)

    @property
    def model_payload(self) -> Any | None:
        return self.rendered_payload if self.rendered_payload is not None else self.payload

    @property
    def model_mime_type(self) -> str | None:
        return self.rendered_mime_type or self.mime_type

    def add_annotation(
        self,
        annotation: EnvAnnotation,
        *,
        renderers: list[EnvAnnotationRenderer] | None = None,
    ) -> None:
        self.annotations.append(annotation)

        for renderer in renderers or []:
            renderer(self, annotation)

    def clear_payload(self) -> None:
        self.payload = None
        self.rendered_payload = None

    def to_evidence_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "observation_id": self.observation_id,
            "kind": self.kind,
            "timestamp": self.timestamp,
            "source_id": self.source_id,
            "mime_type": self.mime_type,
            "metadata": self.metadata,
            "annotations": [ann.to_dict() for ann in self.annotations],
        }

        if self.path:
            data["path"] = self.path

        return data

    @classmethod
    def video_frame(
        cls,
        *,
        timestamp: str,
        source_id: str,
        path: str | None = None,
        payload: Any | None = None,
        rendered_payload: Any | None = None,
        rendered_mime_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        annotations: list[EnvAnnotation] | None = None,
    ) -> "EnvObservation":
        return cls(
            kind="video_frame",
            timestamp=timestamp,
            source_id=source_id,
            path=path,
            payload=payload,
            mime_type="image/jpeg",
            rendered_payload=rendered_payload,
            rendered_mime_type=rendered_mime_type,
            metadata=metadata or {},
            annotations=annotations or [],
        )

    @classmethod
    def video_clip(
        cls,
        *,
        timestamp: str,
        source_id: str,
        path: str | None = None,
        payload: Any | None = None,
        mime_type: str = "video/mp4",
        metadata: dict[str, Any] | None = None,
        annotations: list[EnvAnnotation] | None = None,
    ) -> "EnvObservation":
        return cls(
            kind="video_clip",
            timestamp=timestamp,
            source_id=source_id,
            path=path,
            payload=payload,
            mime_type=mime_type,
            metadata=metadata or {},
            annotations=annotations or [],
        )

    @classmethod
    def audio_segment(
        cls,
        *,
        timestamp: str,
        source_id: str,
        path: str | None = None,
        payload: Any | None = None,
        mime_type: str = "audio/wav",
        metadata: dict[str, Any] | None = None,
        annotations: list[EnvAnnotation] | None = None,
    ) -> "EnvObservation":
        return cls(
            kind="audio_segment",
            timestamp=timestamp,
            source_id=source_id,
            path=path,
            payload=payload,
            mime_type=mime_type,
            metadata=metadata or {},
            annotations=annotations or [],
        )
