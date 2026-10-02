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

from dataclasses import dataclass
from typing import Any

from alphaavatar.core.env import (
    AnnotationKind,
    EnvAnnotation,
    PerceptionEntityRef,
)


@dataclass(frozen=True, slots=True)
class ImagePoint2D:
    x: float
    y: float

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImagePoint2D:
        return cls(x=float(data["x"]), y=float(data["y"]))


@dataclass(frozen=True, slots=True)
class FaceKeypoints5:
    left_eye: ImagePoint2D
    right_eye: ImagePoint2D
    nose: ImagePoint2D
    left_mouth: ImagePoint2D
    right_mouth: ImagePoint2D

    @classmethod
    def from_sequence(
        cls,
        points: list[list[float]] | tuple[tuple[float, float], ...],
    ) -> FaceKeypoints5:
        if len(points) != 5 or any(len(point) != 2 for point in points):
            raise ValueError("FaceKeypoints5 requires exactly five 2D points")

        values = tuple(ImagePoint2D(x=float(point[0]), y=float(point[1])) for point in points)
        return cls(*values)

    def to_dict(self) -> dict[str, Any]:
        return {
            "left_eye": self.left_eye.to_dict(),
            "right_eye": self.right_eye.to_dict(),
            "nose": self.nose.to_dict(),
            "left_mouth": self.left_mouth.to_dict(),
            "right_mouth": self.right_mouth.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FaceKeypoints5:
        return cls(
            left_eye=ImagePoint2D.from_dict(data["left_eye"]),
            right_eye=ImagePoint2D.from_dict(data["right_eye"]),
            nose=ImagePoint2D.from_dict(data["nose"]),
            left_mouth=ImagePoint2D.from_dict(data["left_mouth"]),
            right_mouth=ImagePoint2D.from_dict(data["right_mouth"]),
        )


@dataclass(frozen=True, slots=True)
class FaceDetection:
    bbox: tuple[float, float, float, float]
    detection_confidence: float
    keypoints: FaceKeypoints5 | None = None
    entity: PerceptionEntityRef | None = None

    def __post_init__(self) -> None:
        x1, y1, x2, y2 = self.bbox

        if x2 <= x1 or y2 <= y1:
            raise ValueError("Face bounding box must have positive dimensions")
        if not 0.0 <= self.detection_confidence <= 1.0:
            raise ValueError("detection_confidence must be between zero and one")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "bbox": list(self.bbox),
            "detection_confidence": self.detection_confidence,
        }

        if self.keypoints is not None:
            data["keypoints"] = self.keypoints.to_dict()

        if self.entity is not None:
            data["entity"] = self.entity.to_dict()

        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FaceDetection:
        bbox = data["bbox"]
        keypoints = data.get("keypoints")
        entity = data.get("entity")

        return cls(
            bbox=tuple(float(value) for value in bbox),
            detection_confidence=float(data["detection_confidence"]),
            keypoints=(FaceKeypoints5.from_dict(keypoints) if keypoints is not None else None),
            entity=(PerceptionEntityRef.from_dict(entity) if entity is not None else None),
        )


@dataclass(frozen=True, slots=True)
class FaceDetectionResult:
    image_width: int
    image_height: int
    faces: tuple[FaceDetection, ...]
    selected_face_index: int | None = None

    def __post_init__(self) -> None:
        if self.image_width <= 0 or self.image_height <= 0:
            raise ValueError("Face detection image dimensions must be positive")

        if self.selected_face_index is not None and not 0 <= self.selected_face_index < len(
            self.faces
        ):
            raise ValueError("selected_face_index is outside faces")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "image_width": self.image_width,
            "image_height": self.image_height,
            "faces": [face.to_dict() for face in self.faces],
        }

        if self.selected_face_index is not None:
            data["selected_face_index"] = self.selected_face_index

        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FaceDetectionResult:
        return cls(
            image_width=int(data["image_width"]),
            image_height=int(data["image_height"]),
            faces=tuple(FaceDetection.from_dict(face) for face in data.get("faces", ())),
            selected_face_index=data.get("selected_face_index"),
        )

    @classmethod
    def from_annotation(cls, annotation: EnvAnnotation) -> FaceDetectionResult:
        if annotation.kind != AnnotationKind.FACE_DETECTION:
            raise ValueError(
                f"Expected {AnnotationKind.FACE_DETECTION.value}, got {annotation.kind.value}"
            )

        return cls.from_dict(annotation.data)

    def to_annotation(
        self,
        *,
        source: str,
        observation_id: str,
    ) -> EnvAnnotation:
        return EnvAnnotation(
            source=source,
            kind=AnnotationKind.FACE_DETECTION,
            observation_id=observation_id,
            data=self.to_dict(),
        )
