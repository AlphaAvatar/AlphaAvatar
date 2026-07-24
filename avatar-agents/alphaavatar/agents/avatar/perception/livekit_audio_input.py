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

from alphaavatar.agents.log import logger
from alphaavatar.agents.plugin import AvatarRuntimePlugin
from alphaavatar.agents.utils.id_utils import get_md5_id
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.media import AudioFramePayload
from alphaavatar.core.perception import PerceptionRuntime

from .livekit_audio_codec import from_livekit_audio_frame

if TYPE_CHECKING:
    from alphaavatar.agents.avatar.engine import AvatarEngine


class LiveKitAudioInputRuntime(AvatarRuntimePlugin):
    """
    LiveKit audio input adapter.

    Responsibilities:
    - subscribe to LiveKit audio tracks;
    - normalize incoming RTC audio into a stable sample rate/channel layout;
    - convert rtc.AudioFrame into AlphaAvatar AudioFrame;
    - publish audio_frame observations into PerceptionRuntime.

    It must not run VAD, STT, speaker inference, audio classification, or
    interaction routing.
    """

    def __init__(
        self,
        *,
        engine: AvatarEngine,
        perception_runtime: PerceptionRuntime,
        sample_rate: int = 48_000,
        num_channels: int = 1,
        frame_size_ms: int = 20,
    ) -> None:
        if sample_rate <= 0:
            raise ValueError(f"sample_rate must be positive: {sample_rate}")
        if num_channels <= 0:
            raise ValueError(f"num_channels must be positive: {num_channels}")
        if frame_size_ms <= 0:
            raise ValueError(f"frame_size_ms must be positive: {frame_size_ms}")

        self.engine = engine
        self.perception_runtime = perception_runtime

        self._sample_rate = sample_rate
        self._num_channels = num_channels
        self._frame_size_ms = frame_size_ms

        self._audio_streams: dict[str, rtc.AudioStream] = {}
        self._audio_tasks: set[asyncio.Task[None]] = set()

        self._listeners_registered = False
        self._started = False

    """Helper operations"""

    def _get_room(self) -> rtc.Room | None:
        room = self.engine.livekit_room
        if room is None:
            logger.warning("LiveKit room is not bound to AvatarEngine")
        return room

    def _register_task(self, task: asyncio.Task[None]) -> None:
        self._audio_tasks.add(task)

        def _on_done(completed_task: asyncio.Task[None]) -> None:
            self._audio_tasks.discard(completed_task)

            if completed_task.cancelled():
                return

            try:
                error = completed_task.exception()
            except asyncio.CancelledError:
                return

            if error is not None:
                logger.error(
                    "LiveKit audio background task failed",
                    exc_info=(type(error), error, error.__traceback__),
                )

        task.add_done_callback(_on_done)

    def _build_observation(
        self,
        *,
        frame: rtc.AudioFrame,
        track_sid: str,
        participant_identity: str,
        frame_index: int,
        timestamp: float,
    ) -> EnvObservation:
        timestamp_text = str(timestamp)
        frame_id = get_md5_id(
            [
                self.engine.session_runtime.session_id,
                track_sid,
                str(frame_index),
                timestamp_text,
            ]
        )

        audio_frame = from_livekit_audio_frame(frame)
        metadata: dict[str, Any] = {
            "frame_id": frame_id,
            "track_sid": track_sid,
            "participant_identity": participant_identity,
            "frame_index": frame_index,
            "sample_rate": audio_frame.sample_rate,
            "num_channels": audio_frame.num_channels,
            "samples_per_channel": audio_frame.samples_per_channel,
            "duration_sec": audio_frame.duration_sec,
            "rtc_backend": "livekit",
        }

        payload = AudioFramePayload.create(
            frame=audio_frame,
            frame_id=frame_id,
            metadata=dict(metadata),
        )

        return EnvObservation.audio_frame(
            timestamp=timestamp_text,
            source_id=f"env:audio:{track_sid}",
            payload=payload,
            metadata=metadata,
        )

    def _publish_audio_frame(
        self,
        *,
        frame: rtc.AudioFrame,
        track_sid: str,
        participant_identity: str,
        frame_index: int,
        timestamp: float,
    ) -> None:
        try:
            observation = self._build_observation(
                frame=frame,
                track_sid=track_sid,
                participant_identity=participant_identity,
                frame_index=frame_index,
                timestamp=timestamp,
            )
        except Exception:
            logger.exception(
                "Failed to convert LiveKit audio frame participant=%s track_sid=%s frame_index=%s",
                participant_identity,
                track_sid,
                frame_index,
            )
            return

        self.perception_runtime.publish_observation(observation)

    def _try_attach_existing_audio_tracks(self) -> None:
        room = self._get_room()
        if room is None:
            return

        for participant in room.remote_participants.values():
            for publication in participant.track_publications.values():
                track = publication.track
                if track is None or track.kind != rtc.TrackKind.KIND_AUDIO:
                    continue

                self._create_audio_stream(
                    track=track,
                    track_sid=publication.sid,
                    participant_identity=participant.identity,
                )

    def _register_audio_track_listeners(self) -> None:
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
            if not self._started or track.kind != rtc.TrackKind.KIND_AUDIO:
                return

            self._create_audio_stream(
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
            if track.kind != rtc.TrackKind.KIND_AUDIO:
                return

            task = asyncio.create_task(
                self._aclose_audio_stream(
                    track_sid=publication.sid,
                    participant_identity=participant.identity,
                ),
                name=f"livekit_audio_stream_close:{publication.sid}",
            )
            self._register_task(task)

    def _create_audio_stream(
        self,
        *,
        track: rtc.Track,
        track_sid: str,
        participant_identity: str,
    ) -> None:
        if not self._started or track_sid in self._audio_streams:
            return

        audio_stream = rtc.AudioStream(
            track,
            sample_rate=self._sample_rate,
            num_channels=self._num_channels,
            frame_size_ms=self._frame_size_ms,
        )
        self._audio_streams[track_sid] = audio_stream

        async def read_stream() -> None:
            frame_index = 0

            try:
                async for event in audio_stream:
                    if not self._started:
                        break

                    frame_index += 1
                    self._publish_audio_frame(
                        frame=event.frame,
                        track_sid=track_sid,
                        participant_identity=participant_identity,
                        frame_index=frame_index,
                        timestamp=time.time(),
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Audio stream reader failed participant=%s track_sid=%s",
                    participant_identity,
                    track_sid,
                )
            finally:
                if self._audio_streams.get(track_sid) is audio_stream:
                    self._audio_streams.pop(track_sid, None)

        task = asyncio.create_task(
            read_stream(),
            name=f"livekit_audio_stream_reader:{track_sid}",
        )
        self._register_task(task)

        logger.info(
            "LiveKit audio track attached participant=%s track_sid=%s sample_rate=%s channels=%s",
            participant_identity,
            track_sid,
            self._sample_rate,
            self._num_channels,
        )

    async def _aclose_audio_stream(
        self,
        *,
        track_sid: str,
        participant_identity: str,
    ) -> None:
        audio_stream = self._audio_streams.pop(track_sid, None)
        if audio_stream is None:
            return

        try:
            await audio_stream.aclose()
        except Exception:
            logger.exception(
                "Failed to close audio stream participant=%s track_sid=%s",
                participant_identity,
                track_sid,
            )

    """Runtime operations"""

    async def on_session_start(self) -> None:
        if self._started:
            return

        self._started = True
        self._register_audio_track_listeners()
        self._try_attach_existing_audio_tracks()

        logger.info(
            "LiveKit audio input runtime started session_id=%s sample_rate=%s channels=%s",
            self.engine.session_runtime.session_id,
            self._sample_rate,
            self._num_channels,
        )

    async def on_session_stop(self) -> None:
        if not self._started:
            return

        self._started = False

        streams = list(self._audio_streams.items())
        self._audio_streams.clear()

        for track_sid, audio_stream in streams:
            try:
                await audio_stream.aclose()
            except Exception:
                logger.exception("Failed to close audio stream track_sid=%s", track_sid)

        tasks = list(self._audio_tasks)

        for task in tasks:
            if not task.done():
                task.cancel()

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        self._audio_tasks.clear()

        logger.info(
            "LiveKit audio input runtime stopped session_id=%s",
            self.engine.session_runtime.session_id,
        )
