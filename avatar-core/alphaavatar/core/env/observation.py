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

import uuid
from dataclasses import dataclass, field
from typing import Any

from alphaavatar.core.media import MediaPayload

from .annotation import EnvAnnotation


@dataclass(slots=True)
class EnvObservation:
    """
    Runtime environment observation envelope.

    payload:
        AlphaAvatar-owned MediaPayload.

        It must not directly contain:
        - LiveKit rtc.VideoFrame
        - provider-specific content blocks
        - LangChain message objects

    path:
        Optional persisted evidence path.
    """

    kind: str
    timestamp: str
    source_id: str

    observation_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    path: str | None = None
    mime_type: str | None = None

    payload: MediaPayload | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    metadata: dict[str, Any] = field(default_factory=dict)
    annotations: list[EnvAnnotation] = field(default_factory=list)

    @property
    def frame_id(self) -> str | None:
        metadata_frame_id = self.metadata.get("frame_id")
        if metadata_frame_id:
            return str(metadata_frame_id)

        payload_frame_id = getattr(self.payload, "frame_id", None)
        if payload_frame_id:
            return str(payload_frame_id)

        return None

    @property
    def has_payload(self) -> bool:
        return self.payload is not None and self.payload.has_any

    @property
    def has_persisted_evidence(self) -> bool:
        return bool(self.path)

    def add_annotation(self, annotation: EnvAnnotation) -> bool:
        """
        Add annotation once.

        Returns True when added and False when it already existed.
        """

        for current in self.annotations:
            if current.annotation_id == annotation.annotation_id:
                return False

        self.annotations.append(annotation)
        return True

    def clear_payload(self) -> None:
        if self.payload is not None:
            self.payload.clear()

        self.payload = None

    def to_evidence_dict(self) -> dict[str, Any]:
        if self.path:
            data: dict[str, Any] = {
                "observation_id": self.observation_id,
                "kind": self.kind,
                "timestamp": self.timestamp,
                "source_id": self.source_id,
                "mime_type": self.mime_type,
                "metadata": self.metadata,
                "annotations": [annotation.to_dict() for annotation in self.annotations],
                "path": self.path,
            }

            return data
        else:
            return {}

    @classmethod
    def video_frame(
        cls,
        *,
        timestamp: str,
        source_id: str,
        payload: MediaPayload,
        path: str | None = None,
        metadata: dict[str, Any] | None = None,
        annotations: list[EnvAnnotation] | None = None,
    ) -> EnvObservation:
        return cls(
            kind="video_frame",
            timestamp=timestamp,
            source_id=source_id,
            path=path,
            mime_type="image/jpeg",
            payload=payload,
            metadata=metadata or {},
            annotations=annotations or [],
        )

    @classmethod
    def screen_frame(
        cls,
        *,
        timestamp: str,
        source_id: str,
        payload: MediaPayload,
        path: str | None = None,
        metadata: dict[str, Any] | None = None,
        annotations: list[EnvAnnotation] | None = None,
    ) -> EnvObservation:
        return cls(
            kind="screen_frame",
            timestamp=timestamp,
            source_id=source_id,
            path=path,
            mime_type="image/jpeg",
            payload=payload,
            metadata=metadata or {},
            annotations=annotations or [],
        )

    @classmethod
    def video_clip(
        cls,
        *,
        timestamp: str,
        source_id: str,
        payload: MediaPayload | None = None,
        path: str | None = None,
        mime_type: str = "video/mp4",
        metadata: dict[str, Any] | None = None,
        annotations: list[EnvAnnotation] | None = None,
    ) -> EnvObservation:
        return cls(
            kind="video_clip",
            timestamp=timestamp,
            source_id=source_id,
            path=path,
            mime_type=mime_type,
            payload=payload,
            metadata=metadata or {},
            annotations=annotations or [],
        )

    @classmethod
    def audio_segment(
        cls,
        *,
        timestamp: str,
        source_id: str,
        payload: MediaPayload | None = None,
        path: str | None = None,
        mime_type: str = "audio/wav",
        metadata: dict[str, Any] | None = None,
        annotations: list[EnvAnnotation] | None = None,
    ) -> EnvObservation:
        return cls(
            kind="audio_segment",
            timestamp=timestamp,
            source_id=source_id,
            path=path,
            mime_type=mime_type,
            payload=payload,
            metadata=metadata or {},
            annotations=annotations or [],
        )
