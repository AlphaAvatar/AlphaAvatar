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
from typing import TYPE_CHECKING, Any

from livekit import rtc

from alphaavatar.agents.constants import VIDEO_RTC_INTERVAL_SEC
from alphaavatar.agents.log import logger
from alphaavatar.agents.plugin import AvatarRuntimePlugin
from alphaavatar.agents.utils.id_utils import get_md5_id
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.media import VideoFramePayload
from alphaavatar.core.perception import PerceptionRuntime

from .livekit_video_codec import (
    encode_video_frame_to_jpeg,
    from_livekit_video_frame,
)

if TYPE_CHECKING:
    from alphaavatar.agents.avatar.engine import AvatarEngine


class LiveKitVideoInputRuntime(AvatarRuntimePlugin):
    """
    LiveKit video input adapter.

    Responsibilities:
    - subscribe to LiveKit video tracks;
    - sample incoming RTC video frames;
    - convert rtc.VideoFrame into AlphaAvatar VideoFrame;
    - publish EnvObservation into PerceptionRuntime.

    It must not:
    - publish rtc.VideoFrame into avatar-core;
    - depend on Memory, Persona, or AvatarVision;
    - decide which representation downstream consumers should use.
    """

    def __init__(
        self,
        *,
        engine: AvatarEngine,
        perception_runtime: PerceptionRuntime,
        jpeg_quality: int = 85,
    ) -> None:
        self.engine = engine
        self.perception_runtime = perception_runtime

        self._jpeg_quality = jpeg_quality

        self._video_streams: dict[
            str,
            rtc.VideoStream,
        ] = {}

        # Monotonic timestamps are used only for sampling intervals.
        self._last_publish_ts_by_track: dict[
            str,
            float,
        ] = {}

        self._video_tasks: set[asyncio.Task[None]] = set()

        self._listeners_registered = False
        self._started = False

    """Helper Op"""

    def _get_room(self) -> rtc.Room | None:
        room = self.engine.livekit_room

        if room is None:
            logger.warning("LiveKit room is not bound to AvatarEngine")

        return room

    def _register_task(
        self,
        task: asyncio.Task[None],
    ) -> None:
        self._video_tasks.add(task)

        def _on_done(
            completed_task: asyncio.Task[None],
        ) -> None:
            self._video_tasks.discard(completed_task)

            if completed_task.cancelled():
                return

            try:
                error = completed_task.exception()
            except asyncio.CancelledError:
                return

            if error is not None:
                logger.error(
                    "LiveKit video background task failed",
                    exc_info=(
                        type(error),
                        error,
                        error.__traceback__,
                    ),
                )

        task.add_done_callback(_on_done)

    def _build_observation(
        self,
        *,
        frame: rtc.VideoFrame,
        track_sid: str,
        participant_identity: str,
        frame_index: int,
        timestamp: float,
    ) -> EnvObservation:
        """
        Convert one LiveKit frame into an AlphaAvatar observation.

        The payload initially contains:

            RAW + VIDEO_FRAME
            RAW + IMAGE_JPEG_BYTES

        FaceStream may later add:

            ANNOTATED + VIDEO_FRAME
            ANNOTATED + IMAGE_JPEG_BYTES
        """

        timestamp_text = str(timestamp)

        frame_id = get_md5_id(
            [
                self.engine.session_runtime.session_id,
                track_sid,
                str(frame_index),
                timestamp_text,
            ]
        )

        generic_frame = from_livekit_video_frame(frame)

        jpeg_bytes = encode_video_frame_to_jpeg(
            generic_frame,
            jpeg_quality=self._jpeg_quality,
        )

        metadata: dict[str, Any] = {
            "frame_id": frame_id,
            "track_sid": track_sid,
            "participant_identity": (participant_identity),
            "frame_index": frame_index,
            "rtc_backend": "livekit",
        }

        payload = VideoFramePayload.create(
            frame=generic_frame,
            frame_id=frame_id,
            jpeg_bytes=jpeg_bytes,
            metadata=dict(metadata),
        )

        return EnvObservation.video_frame(
            timestamp=timestamp_text,
            source_id=f"env:camera:{track_sid}",
            payload=payload,
            metadata=metadata,
        )

    def _publish_video_frame(
        self,
        *,
        frame: rtc.VideoFrame,
        track_sid: str,
        participant_identity: str,
        frame_index: int,
        timestamp: float,
    ) -> None:
        try:
            observation = self._build_observation(
                frame=frame,
                track_sid=track_sid,
                participant_identity=(participant_identity),
                frame_index=frame_index,
                timestamp=timestamp,
            )

        except Exception:
            logger.exception(
                "Failed to convert LiveKit video frame participant=%s track_sid=%s frame_index=%s",
                participant_identity,
                track_sid,
                frame_index,
            )
            return

        self.perception_runtime.publish_observation(observation)

    def _try_attach_existing_video_tracks(
        self,
    ) -> None:
        room = self._get_room()
        if room is None:
            return

        for participant in room.remote_participants.values():
            for publication in participant.track_publications.values():
                track = publication.track

                if track is None or track.kind != rtc.TrackKind.KIND_VIDEO:
                    continue

                self._create_video_stream(
                    track=track,
                    track_sid=publication.sid,
                    participant_identity=(participant.identity),
                )

    def _register_video_track_listeners(
        self,
    ) -> None:
        if self._listeners_registered:
            return

        room = self._get_room()
        if room is None:
            return

        self._listeners_registered = True

        @room.on("track_subscribed")
        def on_track_subscribed(
            track: rtc.Track,
            publication: rtc.RemoteTrackPublication,
            participant: rtc.RemoteParticipant,
        ) -> None:
            if not self._started:
                return

            if track.kind != rtc.TrackKind.KIND_VIDEO:
                return

            self._create_video_stream(
                track=track,
                track_sid=publication.sid,
                participant_identity=(participant.identity),
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
                    participant_identity=(participant.identity),
                ),
                name=(f"livekit_video_stream_close:{publication.sid}"),
            )

            self._register_task(task)

    def _create_video_stream(
        self,
        *,
        track: rtc.Track,
        track_sid: str,
        participant_identity: str,
    ) -> None:
        if not self._started:
            return

        if track_sid in self._video_streams:
            return

        video_stream = rtc.VideoStream(track)
        self._video_streams[track_sid] = video_stream

        async def read_stream() -> None:
            frame_index = 0

            try:
                async for event in video_stream:
                    if not self._started:
                        break

                    frame_index += 1

                    # Use monotonic time for interval comparison.
                    publish_clock = time.monotonic()

                    last_publish_clock = self._last_publish_ts_by_track.get(track_sid)

                    if (
                        last_publish_clock is not None
                        and publish_clock - last_publish_clock < VIDEO_RTC_INTERVAL_SEC
                    ):
                        continue

                    self._last_publish_ts_by_track[track_sid] = publish_clock

                    # Use wall-clock timestamp for observations and persistence.
                    timestamp = time.time()

                    self._publish_video_frame(
                        frame=event.frame,
                        track_sid=track_sid,
                        participant_identity=(participant_identity),
                        frame_index=frame_index,
                        timestamp=timestamp,
                    )

            except asyncio.CancelledError:
                raise

            except Exception:
                logger.exception(
                    "Video stream reader failed participant=%s track_sid=%s",
                    participant_identity,
                    track_sid,
                )

            finally:
                current_stream = self._video_streams.get(track_sid)

                # Avoid removing a newer stream if the same track SID was
                # recreated before this task finished.
                if current_stream is video_stream:
                    self._video_streams.pop(
                        track_sid,
                        None,
                    )

                self._last_publish_ts_by_track.pop(
                    track_sid,
                    None,
                )

        task = asyncio.create_task(
            read_stream(),
            name=(f"livekit_video_stream_reader:{track_sid}"),
        )

        self._register_task(task)

    async def _aclose_video_stream(
        self,
        *,
        track_sid: str,
        participant_identity: str,
    ) -> None:
        video_stream = self._video_streams.pop(
            track_sid,
            None,
        )

        self._last_publish_ts_by_track.pop(
            track_sid,
            None,
        )

        if video_stream is None:
            return

        try:
            await video_stream.aclose()

        except Exception:
            logger.exception(
                "Failed to close video stream participant=%s track_sid=%s",
                participant_identity,
                track_sid,
            )

    """Runtime Op"""

    async def on_session_start(self) -> None:
        if self._started:
            return

        self._started = True

        self._register_video_track_listeners()
        self._try_attach_existing_video_tracks()

        logger.info(
            "LiveKit video input runtime started session_id=%s sample_interval=%ss",
            self.engine.session_runtime.session_id,
            VIDEO_RTC_INTERVAL_SEC,
        )

    async def on_session_stop(self) -> None:
        if not self._started:
            return

        # Prevent event callbacks and read loops from creating/publishing
        # additional frames while shutdown is in progress.
        self._started = False

        streams = list(self._video_streams.items())

        self._video_streams.clear()
        self._last_publish_ts_by_track.clear()

        for track_sid, video_stream in streams:
            try:
                await video_stream.aclose()

            except Exception:
                logger.exception(
                    "Failed to close video stream track_sid=%s",
                    track_sid,
                )

        tasks = list(self._video_tasks)

        for task in tasks:
            if not task.done():
                task.cancel()

        if tasks:
            await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )

        self._video_tasks.clear()

        logger.info(
            "LiveKit video input runtime stopped session_id=%s",
            self.engine.session_runtime.session_id,
        )
