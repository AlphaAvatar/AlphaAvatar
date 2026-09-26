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

import math
from dataclasses import dataclass

from alphaavatar.agents.avatar.vision import (
    FaceDetection,
    FaceDetectionResult,
    ImagePoint2D,
)


@dataclass(frozen=True, slots=True)
class FaceOrientationEstimate:
    frontal_score: float
    yaw_proxy: float
    pitch_proxy: float
    roll_deg: float
    face_area_ratio: float


def _rotate(
    point: ImagePoint2D,
    *,
    center: ImagePoint2D,
    angle: float,
) -> ImagePoint2D:
    cosine = math.cos(angle)
    sine = math.sin(angle)

    x = point.x - center.x
    y = point.y - center.y

    return ImagePoint2D(
        x=x * cosine - y * sine + center.x,
        y=x * sine + y * cosine + center.y,
    )


def _asymmetry(left: float, right: float) -> float:
    denominator = abs(left) + abs(right)

    if denominator <= 1e-6:
        return 0.0

    return max(-1.0, min(1.0, (left - right) / denominator))


class FaceOrientationEstimator:
    def __init__(
        self,
        *,
        yaw_scale: float = 0.28,
        roll_scale_deg: float = 25.0,
        min_face_area_ratio: float = 0.01,
    ) -> None:
        if yaw_scale <= 0:
            raise ValueError("yaw_scale must be positive")
        if roll_scale_deg <= 0:
            raise ValueError("roll_scale_deg must be positive")
        if not 0.0 <= min_face_area_ratio <= 1.0:
            raise ValueError("min_face_area_ratio must be between zero and one")

        self._yaw_scale = yaw_scale
        self._roll_scale_deg = roll_scale_deg
        self._min_face_area_ratio = min_face_area_ratio

    def estimate(
        self,
        *,
        face: FaceDetection,
        result: FaceDetectionResult,
    ) -> FaceOrientationEstimate | None:
        keypoints = face.keypoints
        if keypoints is None:
            return None

        left_eye = keypoints.left_eye
        right_eye = keypoints.right_eye

        eye_center = ImagePoint2D(
            x=(left_eye.x + right_eye.x) / 2,
            y=(left_eye.y + right_eye.y) / 2,
        )

        roll = math.atan2(
            right_eye.y - left_eye.y,
            right_eye.x - left_eye.x,
        )

        leveled = tuple(
            _rotate(
                point,
                center=eye_center,
                angle=-roll,
            )
            for point in (
                keypoints.left_eye,
                keypoints.right_eye,
                keypoints.nose,
                keypoints.left_mouth,
                keypoints.right_mouth,
            )
        )

        (
            left_eye,
            right_eye,
            nose,
            left_mouth,
            right_mouth,
        ) = leveled

        eye_left_span = nose.x - left_eye.x
        eye_right_span = right_eye.x - nose.x

        mouth_left_span = nose.x - left_mouth.x
        mouth_right_span = right_mouth.x - nose.x

        yaw_proxy = 0.7 * _asymmetry(eye_left_span, eye_right_span) + 0.3 * _asymmetry(
            mouth_left_span, mouth_right_span
        )

        mouth_center_y = (left_mouth.y + right_mouth.y) / 2

        upper_span = nose.y - eye_center.y
        lower_span = mouth_center_y - nose.y
        pitch_proxy = _asymmetry(upper_span, lower_span)

        roll_deg = math.degrees(roll)

        x1, y1, x2, y2 = face.bbox
        face_area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        image_area = result.image_width * result.image_height
        face_area_ratio = face_area / image_area

        pose_distance = (yaw_proxy / self._yaw_scale) ** 2 + (roll_deg / self._roll_scale_deg) ** 2

        pose_score = math.exp(-0.5 * pose_distance)

        if self._min_face_area_ratio:
            size_score = min(
                1.0,
                face_area_ratio / self._min_face_area_ratio,
            )
        else:
            size_score = 1.0

        detection_score = 0.5 + 0.5 * face.detection_confidence

        frontal_score = max(
            0.0,
            min(
                1.0,
                pose_score * size_score * detection_score,
            ),
        )

        return FaceOrientationEstimate(
            frontal_score=frontal_score,
            yaw_proxy=yaw_proxy,
            pitch_proxy=pitch_proxy,
            roll_deg=roll_deg,
            face_area_ratio=face_area_ratio,
        )
