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
import time

import cv2
import numpy as np
from livekit import rtc
from livekit.agents import get_job_context

from alphaavatar.agents.constants import VIDEO_RTC_INTERVAL_SEC
from alphaavatar.agents.log import logger
from alphaavatar.agents.plugin import AvatarRuntimePlugin
from alphaavatar.agents.runtime import SessionRuntime
from alphaavatar.agents.utils.id_utils import get_md5_id
from alphaavatar.core.perception import FrameEvent


class LiveKitVideoInputRuntime(AvatarRuntimePlugin):
    def __init__(self, *, session_runtime: SessionRuntime) -> None:
        self.session_runtime = session_runtime

        self._video_streams: dict[str, rtc.VideoStream] = {}
        self._last_publish_ts_by_track: dict[str, float] = {}
        self._video_tasks: set[asyncio.Task[None]] = set()
        self._listeners_registered = False

    """Helper Op"""

    def _encode_frame_to_jpeg(self, frame: rtc.VideoFrame, *, quality: int = 85) -> bytes:
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
            [int(cv2.IMWRITE_JPEG_QUALITY), quality],
        )
        if not ok:
            raise RuntimeError("Failed to encode video frame to JPEG")

        return encoded.tobytes()

    def _try_attach_existing_video_tracks(self) -> None:
        try:
            room = get_job_context().room
        except Exception as e:
            logger.warning("Cannot access LiveKit room for video input: %s", e)
            return

        for participant in room.remote_participants.values():
            for publication in participant.track_publications.values():
                track = publication.track
                if track is None or track.kind != rtc.TrackKind.KIND_VIDEO:
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
            logger.warning("Cannot register video track listeners: %s", e)
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
            task.add_done_callback(lambda t: self._video_tasks.discard(t))

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
            frame_index = 0

            try:
                async for event in video_stream:
                    frame_index += 1

                    now = time.time()

                    last_publish_ts = self._last_publish_ts_by_track.get(track_sid)
                    if (
                        last_publish_ts is not None
                        and now - last_publish_ts < VIDEO_RTC_INTERVAL_SEC
                    ):
                        continue

                    self._last_publish_ts_by_track[track_sid] = now

                    frame = event.frame
                    timestamp = str(now)
                    frame_id = get_md5_id(
                        [
                            self.session_runtime.session_id,
                            track_sid,
                            str(frame_index),
                            timestamp,
                        ]
                    )

                    try:
                        model_frame_bytes = self._encode_frame_to_jpeg(frame)
                    except Exception as e:
                        logger.warning(
                            "Failed to encode video frame for model input track_sid=%s error=%s",
                            track_sid,
                            e,
                        )
                        model_frame_bytes = None

                    self.session_runtime.perception_bus.publish_frame(
                        FrameEvent(
                            frame_id=frame_id,
                            timestamp=timestamp,
                            source_id=f"env:camera:{track_sid}",
                            payload=frame,  # realtime consumers: Vision / Persona
                            rendered_payload=model_frame_bytes,  # model consumers: Memory / Gemini
                            rendered_mime_type="image/jpeg" if model_frame_bytes else None,
                            mime_type="image/jpeg",
                            metadata={
                                "frame_id": frame_id,
                                "track_sid": track_sid,
                                "participant_identity": participant_identity,
                                "frame_index": frame_index,
                            },
                        )
                    )

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(
                    "Video stream reader failed participant=%s track_sid=%s error=%s",
                    participant_identity,
                    track_sid,
                    e,
                )
            finally:
                self._video_streams.pop(track_sid, None)

        task = asyncio.create_task(read_stream())
        self._video_tasks.add(task)
        task.add_done_callback(lambda t: self._video_tasks.discard(t))

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
                "Failed to close video stream participant=%s track_sid=%s error=%s",
                participant_identity,
                track_sid,
                e,
            )

    """Runtime Op"""

    async def on_session_start(self, **kwargs) -> None:
        self._try_attach_existing_video_tracks()
        self._register_video_track_listeners()

    async def on_session_stop(self, **kwargs) -> None:
        streams = list(self._video_streams.items())
        self._video_streams.clear()
        self._last_publish_ts_by_track.clear()

        for _track_sid, video_stream in streams:
            try:
                await video_stream.aclose()
            except Exception as e:
                logger.warning("Failed to close video stream: %s", e)

        for task in list(self._video_tasks):
            task.cancel()

        if self._video_tasks:
            await asyncio.gather(*self._video_tasks, return_exceptions=True)
            self._video_tasks.clear()
