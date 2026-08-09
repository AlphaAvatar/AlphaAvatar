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
from enum import StrEnum
from typing import Any

from alphaavatar.core.media import MediaPayload
from alphaavatar.core.time import RuntimeTimeRange

from .annotation import EnvAnnotation


class ObservationKind(StrEnum):
    VIDEO_FRAME = "video_frame"
    VIDEO_CLIP = "video_clip"
    SCREEN_FRAME = "screen_frame"

    AUDIO_FRAME = "audio_frame"
    AUDIO_SEGMENT = "audio_segment"
    SPEECH_FRAME = "speech_frame"
    SPEECH_SEGMENT = "speech_segment"

    TRANSCRIPT_DELTA = "transcript_delta"
    TRANSCRIPT_SEGMENT = "transcript_segment"
    TEXT_INPUT = "text_input"

    IMAGE_INPUT = "image_input"


@dataclass(slots=True)
class EnvObservation:
    kind: ObservationKind
    time_range: RuntimeTimeRange
    source_id: str
    observation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    path: str | None = None
    mime_type: str | None = None
    payload: MediaPayload | None = field(default=None, repr=False, compare=False)
    metadata: dict[str, Any] = field(default_factory=dict)
    annotations: list[EnvAnnotation] = field(default_factory=list)

    @property
    def timestamp(self) -> str:
        return str(self.time_range.end.unix_seconds)

    @property
    def frame_id(self) -> str | None:
        value = self.metadata.get("frame_id") or getattr(self.payload, "frame_id", None)
        return str(value) if value else None

    @property
    def segment_id(self) -> str | None:
        value = self.metadata.get("segment_id") or getattr(self.payload, "segment_id", None)
        return str(value) if value else None

    @property
    def has_payload(self) -> bool:
        return self.payload is not None and self.payload.has_any

    @property
    def has_persisted_evidence(self) -> bool:
        return bool(self.path)

    def add_annotation(self, annotation: EnvAnnotation) -> bool:
        if any(current.annotation_id == annotation.annotation_id for current in self.annotations):
            return False
        self.annotations.append(annotation)
        return True

    def clear_payload(self) -> None:
        if self.payload is not None:
            self.payload.clear()
        self.payload = None

    def to_evidence_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "observation_id": self.observation_id,
            "kind": self.kind.value,
            "source_id": self.source_id,
            "timestamp": self.timestamp,
            "time_range": {
                "start_unix_ns": self.time_range.start.unix_ns,
                "start_monotonic_ns": self.time_range.start.monotonic_ns,
                "end_unix_ns": self.time_range.end.unix_ns,
                "end_monotonic_ns": self.time_range.end.monotonic_ns,
            },
            "mime_type": self.mime_type,
            "metadata": dict(self.metadata),
            "annotations": [annotation.to_dict() for annotation in self.annotations],
        }
        if self.path:
            data["path"] = self.path
        return data

    @classmethod
    def _create(
        cls,
        *,
        kind: ObservationKind,
        time_range: RuntimeTimeRange,
        source_id: str,
        payload: MediaPayload | None = None,
        path: str | None = None,
        mime_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        annotations: list[EnvAnnotation] | None = None,
    ) -> EnvObservation:
        return cls(
            kind=kind,
            time_range=time_range,
            source_id=source_id,
            path=path,
            mime_type=mime_type,
            payload=payload,
            metadata=metadata or {},
            annotations=annotations or [],
        )

    @classmethod
    def video_frame(cls, **kwargs: Any) -> EnvObservation:
        kwargs.setdefault("mime_type", "image/jpeg")
        return cls._create(kind=ObservationKind.VIDEO_FRAME, **kwargs)

    @classmethod
    def screen_frame(cls, **kwargs: Any) -> EnvObservation:
        kwargs.setdefault("mime_type", "image/jpeg")
        return cls._create(kind=ObservationKind.SCREEN_FRAME, **kwargs)

    @classmethod
    def video_clip(cls, **kwargs: Any) -> EnvObservation:
        kwargs.setdefault("mime_type", "video/mp4")
        return cls._create(kind=ObservationKind.VIDEO_CLIP, **kwargs)

    @classmethod
    def audio_frame(cls, **kwargs: Any) -> EnvObservation:
        kwargs.setdefault("mime_type", "audio/pcm")
        return cls._create(kind=ObservationKind.AUDIO_FRAME, **kwargs)

    @classmethod
    def audio_segment(cls, **kwargs: Any) -> EnvObservation:
        kwargs.setdefault("mime_type", "audio/pcm")
        return cls._create(kind=ObservationKind.AUDIO_SEGMENT, **kwargs)

    @classmethod
    def speech_frame(cls, **kwargs: Any) -> EnvObservation:
        kwargs.setdefault("mime_type", "audio/pcm")
        return cls._create(kind=ObservationKind.SPEECH_FRAME, **kwargs)

    @classmethod
    def speech_segment(cls, **kwargs: Any) -> EnvObservation:
        kwargs.setdefault("mime_type", "audio/pcm")
        return cls._create(kind=ObservationKind.SPEECH_SEGMENT, **kwargs)

    @classmethod
    def transcript_delta(cls, **kwargs: Any) -> EnvObservation:
        kwargs.setdefault("mime_type", "text/plain")
        return cls._create(kind=ObservationKind.TRANSCRIPT_DELTA, **kwargs)

    @classmethod
    def transcript_segment(cls, **kwargs: Any) -> EnvObservation:
        kwargs.setdefault("mime_type", "text/plain")
        return cls._create(kind=ObservationKind.TRANSCRIPT_SEGMENT, **kwargs)

    @classmethod
    def text_input(cls, **kwargs: Any) -> EnvObservation:
        kwargs.setdefault("mime_type", "text/plain")
        return cls._create(kind=ObservationKind.TEXT_INPUT, **kwargs)

    @classmethod
    def image_input(cls, **kwargs: Any) -> EnvObservation:
        kwargs.setdefault("mime_type", "image/*")
        return cls._create(kind=ObservationKind.IMAGE_INPUT, **kwargs)
