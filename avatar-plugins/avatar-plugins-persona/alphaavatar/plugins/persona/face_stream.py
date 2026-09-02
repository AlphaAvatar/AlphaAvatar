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

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from alphaavatar.agents.avatar.vision import (
    FaceDetection,
    FaceDetectionResult,
    FaceKeypoints5,
)
from alphaavatar.agents.constants import (
    FACE_INFERENCE_THRESHOLD,
    FACE_MATCH_THRESHOLD,
    VIDEO_PERSONA_INTERVAL_SEC,
)
from alphaavatar.agents.entrypoints.livekit import (
    bgr_to_video_frame,
    video_frame_to_bgr,
)
from alphaavatar.agents.persona import (
    FaceStreamBase,
    PersonaBase,
    VectorRunnerOP,
)
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.utils import NumpyOP
from alphaavatar.core.env import (
    AnnotationKind,
    EnvAnnotation,
    EnvObservation,
    ObservationKind,
    PerceptionSourceRef,
)
from alphaavatar.core.media import (
    PayloadFormat,
    PayloadFormatUnavailable,
    PayloadView,
    VideoFrame,
)
from alphaavatar.core.perception import PerceptionStreamKind

from .log import logger
from .model_files import FACE_MODEL_CONFIG
from .runner.face_analysis_runner import FaceAnalysisRunner


@dataclass(slots=True)
class FaceFrameJob:
    observation: EnvObservation


class FaceStreamWrapper(FaceStreamBase):
    CONSUMER_ID = "persona.face_stream"
    SOURCE = "persona.face_stream"

    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        activity_persona: PersonaBase,
    ) -> None:
        super().__init__(
            runtime=runtime,
            activity_persona=activity_persona,
        )

        self._face_config = FACE_MODEL_CONFIG[FaceAnalysisRunner.MODEL_TYPE]

        self._last_sample_ts: dict[PerceptionSourceRef, float] = {}

        self._det_score_threshold = self._face_config.det_thresh
        self._min_face_size = self._face_config.min_face_size
        self._jpeg_quality = self._face_config.jpeg_quality

        # Keep the queue small. For realtime identity detection, the newest
        # frame is generally more useful than accumulated stale frames.
        self._frame_q: asyncio.Queue[FaceFrameJob] = asyncio.Queue(maxsize=2)

        self._worker_task: asyncio.Task[None] | None = None
        self._poll_task: asyncio.Task[None] | None = None

        self._renderer_registered = False

    @property
    def vdb_inference_method(self) -> str:
        method = os.getenv("PERSONA_VDB_INFERENCE_METHOD")
        if not method:
            raise RuntimeError(
                "PERSONA_VDB_INFERENCE_METHOD is not configured. "
                "Make sure the Persona VDB runner is registered before "
                "FaceStreamWrapper starts."
            )
        return method

    """Observation helpers"""

    def _enqueue_latest(self, job: FaceFrameJob) -> bool:
        try:
            self._frame_q.put_nowait(job)
            return True

        except asyncio.QueueFull:
            try:
                self._frame_q.get_nowait()
            except asyncio.QueueEmpty:
                pass

            try:
                self._frame_q.put_nowait(job)
                return True
            except asyncio.QueueFull:
                return False

    def _maybe_enqueue_observation(self, observation: EnvObservation) -> None:
        if observation.kind != ObservationKind.VIDEO_FRAME:
            return

        payload = observation.payload
        if payload is None or not payload.has(
            PayloadFormat.IMAGE_JPEG_BYTES,
            view=PayloadView.RAW,
            fallback_to_raw=False,
        ):
            return

        timestamp = observation.time_range.end.monotonic_ns / 1_000_000_000
        source = observation.source
        last_ts = self._last_sample_ts.get(source, 0.0)

        if VIDEO_PERSONA_INTERVAL_SEC > 0 and timestamp - last_ts < VIDEO_PERSONA_INTERVAL_SEC:
            return

        if not self._enqueue_latest(FaceFrameJob(observation=observation)):
            logger.debug(
                "Face frame queue full; drop frame source_id=%s generation=%s frame_id=%s",
                source.source_id,
                source.source_generation,
                observation.frame_id,
            )
            return

        self._last_sample_ts[source] = timestamp

    def _select_best_face(self, faces: list[dict[str, Any]]) -> dict[str, Any] | None:
        candidates: list[
            tuple[
                float,
                float,
                dict[str, Any],
            ]
        ] = []

        for face in faces:
            bbox = face.get("bbox")
            det_score = float(face.get("det_score") or 0.0)

            if bbox is None or len(bbox) != 4:
                continue

            if det_score < self._det_score_threshold:
                continue

            x1, y1, x2, y2 = [float(x) for x in bbox]
            width = max(0.0, x2 - x1)
            height = max(0.0, y2 - y1)

            if width < self._min_face_size or height < self._min_face_size:
                continue

            area = width * height
            candidates.append((det_score, area, face))

        if not candidates:
            return None

        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return candidates[0][2]

    """Annotation operations"""

    def _safe_face_annotations(
        self,
        faces: list[dict[str, Any]],
        *,
        selected_face: dict[str, Any] | None,
        observation: EnvObservation,
    ) -> tuple[tuple[FaceDetection, ...], int | None]:
        safe_faces: list[FaceDetection] = []
        selected_index: int | None = None

        for face in faces:
            bbox = face.get("bbox")
            if bbox is None or len(bbox) != 4:
                continue

            keypoints = face.get("kps")

            if face is selected_face:
                selected_index = len(safe_faces)

            safe_faces.append(
                FaceDetection(
                    bbox=tuple(float(value) for value in bbox),
                    detection_confidence=float(face.get("det_score") or 0.0),
                    keypoints=(
                        FaceKeypoints5.from_sequence(keypoints) if keypoints is not None else None
                    ),
                    entity=(observation.entity if face is selected_face else None),
                )
            )

        return tuple(safe_faces), selected_index

    def _publish_face_annotation(
        self,
        *,
        job: FaceFrameJob,
        faces: list[dict[str, Any]],
        selected_face: dict[str, Any] | None,
        image_width: int,
        image_height: int,
    ) -> None:
        safe_faces, selected_index = self._safe_face_annotations(
            faces,
            selected_face=selected_face,
            observation=job.observation,
        )

        if not safe_faces:
            return

        result = FaceDetectionResult(
            image_width=image_width,
            image_height=image_height,
            faces=safe_faces,
            selected_face_index=selected_index,
        )

        self.perception_runtime.publish_annotation(
            result.to_annotation(
                source=self.SOURCE,
                observation_id=job.observation.observation_id,
            )
        )

    def _render_face_annotation(
        self,
        observation: EnvObservation,
        annotation: EnvAnnotation,
    ) -> None:
        if annotation.kind != AnnotationKind.FACE_DETECTION:
            return

        payload = observation.payload
        if payload is None:
            return

        try:
            # Prefer an already annotated frame so different renderers can
            # compose overlays instead of overwriting one another.
            source_frame = payload.get(
                PayloadFormat.VIDEO_FRAME,
                view=PayloadView.ANNOTATED,
                fallback_to_raw=True,
            )
        except PayloadFormatUnavailable:
            logger.debug(
                "Cannot render face annotation because VIDEO_FRAME "
                "representation is unavailable observation_id=%s",
                observation.observation_id,
            )
            return

        if not isinstance(source_frame, VideoFrame):
            logger.warning(
                "Cannot render face annotation because VIDEO_FRAME representation "
                "has an invalid type observation_id=%s type=%s",
                observation.observation_id,
                type(source_frame).__name__,
            )
            return

        try:
            bgr = video_frame_to_bgr(source_frame)
        except Exception:
            logger.exception(
                "Failed to convert video frame for face rendering observation_id=%s",
                observation.observation_id,
            )
            return

        result = FaceDetectionResult.from_annotation(annotation)

        for face in result.faces:
            x1, y1, x2, y2 = (int(value) for value in face.bbox)

            cv2.rectangle(bgr, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(
                bgr,
                f"face {face.detection_confidence:.2f}",
                (x1, max(0, y1 - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (0, 255, 0),
                1,
                cv2.LINE_AA,
            )

        try:
            annotated_frame = bgr_to_video_frame(bgr)
        except Exception:
            logger.exception(
                "Failed to build annotated video frame observation_id=%s",
                observation.observation_id,
            )
            return

        ok, encoded = cv2.imencode(
            ".jpg",
            bgr,
            [int(cv2.IMWRITE_JPEG_QUALITY), self._jpeg_quality],
        )
        if not ok:
            logger.warning(
                "Failed to encode annotated face frame observation_id=%s",
                observation.observation_id,
            )
            return

        payload.put(
            PayloadFormat.VIDEO_FRAME,
            annotated_frame,
            view=PayloadView.ANNOTATED,
        )
        payload.put(
            PayloadFormat.IMAGE_JPEG_BYTES,
            encoded.tobytes(),
            view=PayloadView.ANNOTATED,
        )

        rendered_annotations = observation.metadata.setdefault(
            "rendered_annotations",
            [],
        )
        if annotation.annotation_id not in rendered_annotations:
            rendered_annotations.append(annotation.annotation_id)

    """Inference worker"""

    async def _inference_face_job(self, job: FaceFrameJob) -> None:
        start_time = time.perf_counter()

        payload = job.observation.payload
        if payload is None:
            return

        try:
            image_bytes = payload.get(
                PayloadFormat.IMAGE_JPEG_BYTES,
                view=PayloadView.RAW,
                fallback_to_raw=False,
            )
        except PayloadFormatUnavailable:
            logger.debug(
                "Skip face inference because raw JPEG "
                "representation is unavailable observation_id=%s",
                job.observation.observation_id,
            )
            return

        if not isinstance(image_bytes, bytes):
            logger.warning(
                "Skip face inference because JPEG representation "
                "has an invalid type observation_id=%s type=%s",
                job.observation.observation_id,
                type(image_bytes).__name__,
            )
            return

        results = await self.inference_executor.do_inference(
            FaceAnalysisRunner.INFERENCE_METHOD,
            image_bytes,
        )

        data: dict[str, Any] = json.loads(results.decode())
        faces = data.get("faces", [])
        if not faces:
            return

        face = self._select_best_face(faces)
        if face is None:
            self._publish_face_annotation(
                job=job,
                faces=faces,
                selected_face=None,
                image_width=int(data["image_width"]),
                image_height=int(data["image_height"]),
            )
            return

        embedding = face.get("embedding")
        if embedding is None:
            self._publish_face_annotation(
                job=job,
                faces=faces,
                selected_face=face,
                image_width=int(data["image_width"]),
                image_height=int(data["image_height"]),
            )
            return

        inference_duration = time.perf_counter() - start_time
        if inference_duration > FACE_INFERENCE_THRESHOLD:
            logger.warning(
                "[FaceAnalysis] inference is slower than realtime duration=%.3fs threshold=%.3fs",
                inference_duration,
                FACE_INFERENCE_THRESHOLD,
            )

        #  Match & Retrieve & Update Face
        face_vector = np.asarray(embedding, dtype=np.float32)
        uid = await self._activity_persona.match_face_vector(face_vector=face_vector)
        if uid is not None:
            await self._activity_persona.update_face_vector(
                uid=uid,
                face_vector=face_vector,
            )

        else:
            json_data = {
                "op": VectorRunnerOP.search_face_vector,
                "param": {
                    "face_vector": NumpyOP.l2_normalize(face_vector).tolist(),
                    "threshold": (FACE_MATCH_THRESHOLD),
                },
            }

            results = await self.inference_executor.do_inference(
                self.vdb_inference_method,
                json.dumps(json_data).encode(),
            )

            if results:
                match_data = json.loads(results.decode())
                uid = match_data.get("user_id", "")
                if uid:
                    await self._activity_persona.load_profile(uid=uid)
                    await self._activity_persona.update_face_vector(
                        uid=uid,
                        face_vector=face_vector,
                    )

            else:
                uid = await self._activity_persona.insert_face_vector(face_vector=face_vector)

        face_attribute = {
            "age": face.get("age"),
            "gender": face.get("gender"),
            "bbox": face.get("bbox"),
            "det_score": face.get("det_score"),
            "transport_participant_id": job.observation.transport_participant_id,
            "track_sid": job.observation.metadata.get("track_sid"),
            "frame_id": job.observation.frame_id,
            "observation_id": job.observation.observation_id,
        }

        if uid:
            await self._activity_persona.update_face_attribute(
                uid=uid,
                face_attribute=face_attribute,
            )

        self._publish_face_annotation(
            job=job,
            faces=faces,
            selected_face=face,
            image_width=int(data["image_width"]),
            image_height=int(data["image_height"]),
        )

    async def _face_worker(self) -> None:
        while True:
            job = await self._frame_q.get()

            try:
                await self._inference_face_job(job)

            except asyncio.CancelledError:
                raise

            except Exception as error:
                observation = job.observation
                logger.warning(
                    "Face worker failed participant=%s track_sid=%s error=%s",
                    observation.transport_participant_id,
                    observation.metadata.get("track_sid"),
                    error,
                    exc_info=True,
                )

    """Perception consumer"""

    async def _face_observation_loop(self) -> None:
        while True:
            try:
                await self.perception_runtime.wait_for_pending_observations(
                    consumer_id=self.CONSUMER_ID,
                    streams={PerceptionStreamKind.VIDEO, PerceptionStreamKind.SCREEN},
                )

                window = self.perception_runtime.take_pending_observations(
                    consumer_id=self.CONSUMER_ID,
                    streams={PerceptionStreamKind.VIDEO, PerceptionStreamKind.SCREEN},
                    require_payload=True,
                )

                try:
                    if window.has_gap:
                        logger.warning(
                            "Face stream observed visual gap missed=%s",
                            window.missed_count,
                        )

                    for observation in window.observations:
                        try:
                            self._maybe_enqueue_observation(observation)
                        except Exception:
                            logger.exception(
                                "Face stream failed to enqueue observation observation_id=%s",
                                observation.observation_id,
                            )

                finally:
                    self.perception_runtime.commit_observations(window)

            except asyncio.CancelledError:
                raise

            except Exception:
                logger.exception("Face stream failed to consume perception observations")
                await asyncio.sleep(0.05)

    """Runtime operations"""

    async def start(self) -> None:
        if not self._renderer_registered:
            self.perception_runtime.add_annotation_renderer(self._render_face_annotation)
            self._renderer_registered = True

        self._worker_task = asyncio.create_task(
            self._face_worker(),
            name="face_worker",
        )
        self._poll_task = asyncio.create_task(
            self._face_observation_loop(),
            name="face_observation_loop",
        )

        logger.info(
            "Persona face stream started consumer_id=%s",
            self.CONSUMER_ID,
        )

    async def stop(self) -> None:
        # Stop reading new observations first.
        if self._poll_task is not None:
            self._poll_task.cancel()

            await asyncio.gather(
                self._poll_task,
                return_exceptions=True,
            )

            self._poll_task = None

        # Then stop the inference worker.
        if self._worker_task is not None:
            self._worker_task.cancel()

            await asyncio.gather(
                self._worker_task,
                return_exceptions=True,
            )

            self._worker_task = None

        if self._renderer_registered:
            self.perception_runtime.remove_annotation_renderer(self._render_face_annotation)
            self._renderer_registered = False

        while not self._frame_q.empty():
            try:
                self._frame_q.get_nowait()
            except asyncio.QueueEmpty:
                break

        self._last_sample_ts.clear()

        logger.info(
            "Persona face stream stopped consumer_id=%s",
            self.CONSUMER_ID,
        )
