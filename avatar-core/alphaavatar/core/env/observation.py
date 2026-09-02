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
from alphaavatar.core.time import RuntimeTimeRange

from .annotation import EnvAnnotation
from .enum import ObservationKind
from .schema import (
    PerceptionEntityRef,
    PerceptionSegmentRef,
    PerceptionSourceRef,
)

_SEGMENT_REQUIRED_KINDS = {
    ObservationKind.AUDIO_SEGMENT,
    ObservationKind.SPEECH_FRAME,
    ObservationKind.SPEECH_SEGMENT,
    ObservationKind.TRANSCRIPT_DELTA,
    ObservationKind.TRANSCRIPT_SEGMENT,
}

_SPEECH_KINDS = {
    ObservationKind.SPEECH_FRAME,
    ObservationKind.SPEECH_SEGMENT,
}


_RESERVED_METADATA_KEYS = frozenset(
    {
        # Observation identity
        "observation_id",
        "frame_id",
        # Perception source
        "source_id",
        "source_generation",
        "source_kind",
        "modality",
        # Segment lineage
        "segment_id",
        "speech_source_id",
        "speech_source_generation",
        # Transport identity
        "transport_participant_id",
        "participant_identity",
        # Perception / resolved entity identity
        "perception_entity_id",
        "resolved_entity_id",
        # Old / ambiguous identity names that must disappear
        "speaker_perception_id",
        "speaker_entity_id",
        "speaker_track_id",
        "track_id",
    }
)


@dataclass(slots=True)
class EnvObservation:
    kind: ObservationKind
    time_range: RuntimeTimeRange
    source: PerceptionSourceRef

    payload: MediaPayload | None = None
    segment: PerceptionSegmentRef | None = None

    transport_participant_id: str | None = None
    entity: PerceptionEntityRef | None = None

    frame_id: str | None = None
    path: str | None = None
    mime_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    observation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    annotations: list[EnvAnnotation] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.transport_participant_id == "":
            raise ValueError("transport_participant_id cannot be empty")
        if self.frame_id == "":
            raise ValueError("frame_id cannot be empty")

        reserved = self.metadata.keys() & _RESERVED_METADATA_KEYS
        if reserved:
            raise ValueError(
                f"{self.kind.value} metadata contains reserved fields: "
                f"{', '.join(sorted(reserved))}"
            )

        if self.kind in _SEGMENT_REQUIRED_KINDS and self.segment is None:
            raise ValueError(f"{self.kind.value} requires a segment reference")

        if (
            self.kind in _SPEECH_KINDS
            and self.segment is not None
            and self.segment.source != self.source
        ):
            raise ValueError(f"{self.kind.value} segment source must match observation source")

    @property
    def source_id(self) -> str:
        return self.source.source_id

    @property
    def source_generation(self) -> int:
        return self.source.source_generation

    @property
    def segment_id(self) -> str | None:
        return self.segment.segment_id if self.segment is not None else None

    @property
    def timestamp(self) -> str:
        return str(self.time_range.end.unix_seconds)

    @property
    def has_payload(self) -> bool:
        return self.payload is not None and self.payload.has_any

    @classmethod
    def _create(
        cls,
        *,
        kind: ObservationKind,
        time_range: RuntimeTimeRange,
        source: PerceptionSourceRef,
        payload: MediaPayload | None = None,
        segment: PerceptionSegmentRef | None = None,
        transport_participant_id: str | None = None,
        entity: PerceptionEntityRef | None = None,
        frame_id: str | None = None,
        path: str | None = None,
        mime_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        annotations: list[EnvAnnotation] | None = None,
    ) -> EnvObservation:
        return cls(
            kind=kind,
            time_range=time_range,
            source=source,
            payload=payload,
            segment=segment,
            transport_participant_id=transport_participant_id,
            entity=entity,
            frame_id=frame_id,
            path=path,
            mime_type=mime_type,
            metadata=dict(metadata or {}),
            annotations=list(annotations or ()),
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
            "source": self.source.to_dict(),
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

        if self.segment is not None:
            data["segment"] = self.segment.to_dict()

        if self.transport_participant_id is not None:
            data["transport_participant_id"] = self.transport_participant_id

        if self.entity is not None:
            data["entity"] = self.entity.to_dict()

        if self.frame_id is not None:
            data["frame_id"] = self.frame_id

        if self.path is not None:
            data["path"] = self.path

        return data
