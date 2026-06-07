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
import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from livekit import rtc
from livekit.agents.job import get_job_context

from alphaavatar.agents.persona import FaceStreamBase, PersonaBase
from alphaavatar.agents.utils import NumpyOP

from .log import logger
from .models import FACE_MODEL_CONFIG
from .runner.face_analysis_runner import FaceAnalysisRunner


@dataclass
class FaceFrameJob:
    frame: rtc.VideoFrame
    track_sid: str
    participant_identity: str
    timestamp: float


class FaceStreamWrapper(FaceStreamBase):
    def __init__(self, *, activity_persona: PersonaBase) -> None:
        super().__init__(activity_persona=activity_persona)

        self._executor = get_job_context().inference_executor
        self._face_config = FACE_MODEL_CONFIG[FaceAnalysisRunner.MODEL_TYPE]

        self._video_streams: dict[str, rtc.VideoStream] = {}
        self._video_tasks: set[asyncio.Task[None]] = set()
        self._listeners_registered: bool = False

        self._last_sample_ts: dict[str, float] = {}

        self._sample_interval_sec = self._face_config.sample_interval_sec
        self._det_score_threshold = self._face_config.det_thresh
        self._min_face_size = self._face_config.min_face_size
        self._jpeg_quality = self._face_config.jpeg_quality

        # Independent message channel.
        # Keep it small to preserve realtime behavior and avoid memory buildup.
        self._frame_q: asyncio.Queue[FaceFrameJob] = asyncio.Queue(maxsize=2)
        self._worker_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(
                self._face_worker(),
                name="face_worker",
            )

        self._try_attach_existing_video_tracks()
        self._register_video_track_listeners()

    def _try_attach_existing_video_tracks(self) -> None:
        try:
            room = get_job_context().room
        except Exception as e:
            logger.warning("Cannot access LiveKit room for face stream: %s", e)
            return

        for participant in room.remote_participants.values():
            for publication in participant.track_publications.values():
                track = publication.track
                if track is None:
                    continue

                if track.kind != rtc.TrackKind.KIND_VIDEO:
                    continue

                self._create_video_stream(
                    track=track,
                    track_sid=publication.sid,
                    participant_identity=participant.identity,
                )

    def _register_video_track_listeners(self) -> None:
        if self._listeners_registered:
            return

        try:
            room = get_job_context().room
        except Exception as e:
            logger.warning("Cannot register face stream listeners: %s", e)
            return

        self._listeners_registered = True

        @room.on("track_subscribed")
        def on_track_subscribed(
            track: rtc.Track,
            publication: rtc.RemoteTrackPublication,
            participant: rtc.RemoteParticipant,
        ) -> None:
            if track.kind != rtc.TrackKind.KIND_VIDEO:
                return

            self._create_video_stream(
                track=track,
                track_sid=publication.sid,
                participant_identity=participant.identity,
            )

        @room.on("track_unsubscribed")
        def on_track_unsubscribed(
            track: rtc.Track,
            publication: rtc.RemoteTrackPublication,
            participant: rtc.RemoteParticipant,
        ) -> None:
            if track.kind != rtc.TrackKind.KIND_VIDEO:
                return

            task = asyncio.create_task(
                self._aclose_video_stream(
                    track_sid=publication.sid,
                    participant_identity=participant.identity,
                )
            )
            self._video_tasks.add(task)

            def cleanup(done_task: asyncio.Task[None]) -> None:
                self._video_tasks.discard(done_task)
                try:
                    done_task.result()
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.warning(
                        "Face stream close task failed participant=%s track_sid=%s error=%s",
                        participant.identity,
                        publication.sid,
                        e,
                    )

            task.add_done_callback(cleanup)

    def _create_video_stream(
        self,
        *,
        track: rtc.Track,
        track_sid: str,
        participant_identity: str,
    ) -> None:
        if track_sid in self._video_streams:
            return

        video_stream = rtc.VideoStream(track)
        self._video_streams[track_sid] = video_stream

        async def read_stream() -> None:
            try:
                async for event in video_stream:
                    self._maybe_enqueue_frame(
                        frame=event.frame,
                        track_sid=track_sid,
                        participant_identity=participant_identity,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(
                    "Face stream reader failed participant=%s track_sid=%s error=%s",
                    participant_identity,
                    track_sid,
                    e,
                )
            finally:
                self._video_streams.pop(track_sid, None)

        task = asyncio.create_task(read_stream())
        self._video_tasks.add(task)

        def cleanup(done_task: asyncio.Task[None]) -> None:
            self._video_tasks.discard(done_task)
            try:
                done_task.result()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(
                    "Face stream task failed participant=%s track_sid=%s error=%s",
                    participant_identity,
                    track_sid,
                    e,
                )

        task.add_done_callback(cleanup)

        logger.info(
            "Attached face stream participant=%s track_sid=%s",
            participant_identity,
            track_sid,
        )

    def _maybe_enqueue_frame(
        self,
        *,
        frame: rtc.VideoFrame,
        track_sid: str,
        participant_identity: str,
    ) -> None:
        now = time.monotonic()
        last_ts = self._last_sample_ts.get(track_sid, 0.0)

        if self._sample_interval_sec > 0 and now - last_ts < self._sample_interval_sec:
            return

        self._last_sample_ts[track_sid] = now

        job = FaceFrameJob(
            frame=frame,
            track_sid=track_sid,
            participant_identity=participant_identity,
            timestamp=now,
        )

        try:
            self._frame_q.put_nowait(job)
        except asyncio.QueueFull:
            # Drop stale frame first. Face identity should be realtime, not exhaustive.
            try:
                self._frame_q.get_nowait()
            except asyncio.QueueEmpty:
                pass

            try:
                self._frame_q.put_nowait(job)
            except asyncio.QueueFull:
                logger.debug(
                    "Face frame queue full; drop frame participant=%s track_sid=%s",
                    participant_identity,
                    track_sid,
                )

    async def _face_worker(self) -> None:
        while True:
            job = await self._frame_q.get()

            try:
                await self._inference_face_job(job)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(
                    "Face worker failed participant=%s track_sid=%s error=%s",
                    job.participant_identity,
                    job.track_sid,
                    e,
                )

    def _encode_frame_to_jpeg(self, frame: rtc.VideoFrame) -> bytes:
        rgba = frame.convert(rtc.VideoBufferType.RGBA)
        arr = np.frombuffer(rgba.data, dtype=np.uint8).reshape(
            rgba.height,
            rgba.width,
            4,
        )
        bgr = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)

        ok, encoded = cv2.imencode(
            ".jpg",
            bgr,
            [int(cv2.IMWRITE_JPEG_QUALITY), self._jpeg_quality],
        )
        if not ok:
            raise RuntimeError("Failed to encode video frame to JPEG")

        return encoded.tobytes()

    def _select_best_face(self, faces: list[dict[str, Any]]) -> dict[str, Any] | None:
        candidates = []

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

    async def _inference_face_job(self, job: FaceFrameJob) -> None:
        image_bytes = self._encode_frame_to_jpeg(job.frame)

        results = await asyncio.wait_for(
            self._executor.do_inference(
                FaceAnalysisRunner.INFERENCE_METHOD,
                image_bytes,
            ),
            timeout=self._face_config.inference_timeout_sec,
        )

        data: dict[str, Any] = json.loads(results.decode())
        faces = data.get("faces", [])
        if not faces:
            return

        face = self._select_best_face(faces)
        if face is None:
            return

        embedding = face.get("embedding")
        if embedding is None:
            return

        face_vector = NumpyOP.l2_normalize(np.asarray(embedding, dtype=np.float32))

        uid = await self._activity_persona.match_face_vector(face_vector=face_vector)

        if uid is not None:
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
            "participant_identity": job.participant_identity,
            "track_sid": job.track_sid,
        }
        await self._activity_persona.update_face_attribute(
            uid=uid,
            face_attribute=face_attribute,
        )

        logger.info(
            "Face identity updated uid=%s participant=%s track_sid=%s det_score=%s age=%s gender=%s",
            uid,
            job.participant_identity,
            job.track_sid,
            face.get("det_score"),
            face.get("age"),
            face.get("gender"),
        )

    async def _aclose_video_stream(
        self,
        *,
        track_sid: str,
        participant_identity: str,
    ) -> None:
        video_stream = self._video_streams.pop(track_sid, None)
        if video_stream is None:
            return

        try:
            await video_stream.aclose()
        except Exception as e:
            logger.warning(
                "Failed to close face stream participant=%s track_sid=%s error=%s",
                participant_identity,
                track_sid,
                e,
            )
            return

        logger.info(
            "Closed face stream participant=%s track_sid=%s",
            participant_identity,
            track_sid,
        )

    async def stop(self) -> None:
        streams = list(self._video_streams.items())
        self._video_streams.clear()

        for track_sid, video_stream in streams:
            try:
                await video_stream.aclose()
            except Exception as e:
                logger.warning(
                    "Failed to close face stream track_sid=%s error=%s",
                    track_sid,
                    e,
                )

        for task in list(self._video_tasks):
            task.cancel()

        if self._video_tasks:
            await asyncio.gather(*self._video_tasks, return_exceptions=True)
            self._video_tasks.clear()

        if self._worker_task is not None:
            self._worker_task.cancel()
            await asyncio.gather(self._worker_task, return_exceptions=True)
            self._worker_task = None

        while not self._frame_q.empty():
            try:
                self._frame_q.get_nowait()
            except asyncio.QueueEmpty:
                break

        self._last_sample_ts.clear()
