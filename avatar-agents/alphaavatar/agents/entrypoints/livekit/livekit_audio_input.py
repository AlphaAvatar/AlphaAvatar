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
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any

from alphaavatar.agents.log import logger
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.runtime.plugin import AvatarRuntimePlugin
from alphaavatar.agents.utils.id_utils import get_md5_id
from alphaavatar.core.env import EnvObservation, PerceptionSourceRef
from alphaavatar.core.media import AudioFramePayload
from alphaavatar.core.perception import (
    MediaModality,
    MediaSourceKind,
    MediaSourceState,
    MediaSourceStateEvent,
)
from alphaavatar.core.time import RuntimeTime, RuntimeTimeRange
from livekit import rtc

from .livekit_audio_codec import from_livekit_audio_frame


@dataclass(slots=True)
class _AudioTrackBinding:
    track_sid: str
    track_name: str
    track_source: int

    source: PerceptionSourceRef
    transport_participant_id: str

    publication: rtc.RemoteTrackPublication
    stream: rtc.AudioStream
    state: MediaSourceState | None = None
    reader_task: asyncio.Task[None] | None = None

    @property
    def source_id(self) -> str:
        return self.source.source_id

    @property
    def source_generation(self) -> int:
        return self.source.source_generation


class LiveKitAudioInput(AvatarRuntimePlugin):
    """Translate LiveKit microphone tracks into audio observations and source-state events."""

    def __init__(
        self,
        *,
        room: rtc.Room,
        runtime: AvatarRuntime,
        frame_size_ms: int,
        sample_rate: int = 48_000,
        num_channels: int = 1,
    ) -> None:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if num_channels <= 0:
            raise ValueError("num_channels must be positive")
        if frame_size_ms <= 0:
            raise ValueError("frame_size_ms must be positive")

        self._room = room
        self._runtime = runtime
        self._sample_rate = sample_rate
        self._num_channels = num_channels
        self._frame_size_ms = frame_size_ms
        self._bindings: dict[str, _AudioTrackBinding] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._listeners_registered = False
        self._started = False

    def _spawn(self, coroutine: Coroutine[Any, Any, None], *, name: str) -> asyncio.Task[None]:
        task = asyncio.create_task(coroutine, name=name)
        self._tasks.add(task)

        def on_done(completed: asyncio.Task[None]) -> None:
            self._tasks.discard(completed)
            if completed.cancelled():
                return
            error = completed.exception()
            if error is not None:
                logger.error(
                    "LiveKit audio background task failed task=%s",
                    completed.get_name(),
                    exc_info=(type(error), error, error.__traceback__),
                )

        task.add_done_callback(on_done)
        return task

    @staticmethod
    def _source_id(
        participant_identity: str,
        track_sid: str,
        track_source: int,
    ) -> str:
        owner = participant_identity or "anonymous"
        discriminator = f"source:{track_source}" if track_source else f"track:{track_sid}"
        return f"env:audio:{owner}:{discriminator}"

    def _publish_source_state(
        self,
        binding: _AudioTrackBinding,
        state: MediaSourceState,
        *,
        reason: str,
    ) -> None:
        if binding.state == state:
            return
        binding.state = state
        self._runtime.perception.publish_source_state(
            MediaSourceStateEvent(
                source=binding.source,
                modality=MediaModality.AUDIO,
                source_kind=MediaSourceKind.MICROPHONE,
                state=state,
                transport_participant_id=binding.transport_participant_id,
                reason=reason,
                metadata={
                    "rtc_backend": "livekit",
                    "track_sid": binding.track_sid,
                    "track_name": binding.track_name,
                    "track_source": binding.track_source,
                },
            )
        )
        logger.info(
            "LiveKit audio source state source_id=%s generation=%s state=%s reason=%s",
            binding.source_id,
            binding.source_generation,
            state.value,
            reason,
        )

    def _binding_for_publication(
        self,
        publication: rtc.RemoteTrackPublication,
    ) -> _AudioTrackBinding | None:
        binding = self._bindings.get(publication.sid)
        return binding if binding is not None and binding.publication is publication else None

    def _detach_binding(
        self,
        binding: _AudioTrackBinding,
        *,
        state: MediaSourceState,
        reason: str,
    ) -> bool:
        if self._bindings.get(binding.track_sid) is not binding:
            return False
        self._bindings.pop(binding.track_sid)
        self._publish_source_state(binding, state, reason=reason)
        return True

    def _detach_publication(
        self,
        publication: rtc.RemoteTrackPublication,
        *,
        state: MediaSourceState,
        reason: str,
    ) -> _AudioTrackBinding | None:
        binding = self._binding_for_publication(publication)
        return (
            binding
            if binding and self._detach_binding(binding, state=state, reason=reason)
            else None
        )

    def _schedule_close(self, binding: _AudioTrackBinding | None) -> None:
        if binding is not None:
            self._spawn(
                self._close_binding(binding),
                name=f"livekit_audio_close:{binding.track_sid}:{binding.source_generation}",
            )

    def _build_observation(
        self,
        *,
        binding: _AudioTrackBinding,
        frame: rtc.AudioFrame,
        frame_index: int,
        ended_at: RuntimeTime,
    ) -> EnvObservation:
        audio_frame = from_livekit_audio_frame(frame)
        time_range = RuntimeTimeRange(
            start=ended_at.shifted(-audio_frame.duration_sec),
            end=ended_at,
        )
        frame_id = get_md5_id(
            [
                self._runtime.session.session_id,
                binding.track_sid,
                str(binding.source_generation),
                str(frame_index),
                str(ended_at.unix_ns),
            ]
        )

        payload = AudioFramePayload.create(
            frame=audio_frame,
            frame_id=frame_id,
        )
        return EnvObservation.audio_frame(
            time_range=time_range,
            source=binding.source,
            frame_id=frame_id,
            transport_participant_id=binding.transport_participant_id,
            payload=payload,
            metadata={
                "track_sid": binding.track_sid,
                "track_name": binding.track_name,
                "track_source": binding.track_source,
                "frame_index": frame_index,
                "sample_rate": audio_frame.sample_rate,
                "num_channels": audio_frame.num_channels,
                "samples_per_channel": audio_frame.samples_per_channel,
                "duration_sec": audio_frame.duration_sec,
                "rtc_backend": "livekit",
            },
        )

    async def _read_stream(self, binding: _AudioTrackBinding) -> None:
        frame_index = 0
        terminal_state = MediaSourceState.ENDED
        terminal_reason = "reader_ended"
        try:
            async for event in binding.stream:
                if not self._started or self._bindings.get(binding.track_sid) is not binding:
                    break
                if binding.state == MediaSourceState.MUTED:
                    continue
                frame_index += 1
                ended_at = self._runtime.clock.now()
                try:
                    observation = self._build_observation(
                        binding=binding,
                        frame=event.frame,
                        frame_index=frame_index,
                        ended_at=ended_at,
                    )
                except Exception:
                    logger.exception(
                        "Failed to convert LiveKit audio frame participant=%s track_sid=%s "
                        "generation=%s frame_index=%s",
                        binding.transport_participant_id,
                        binding.track_sid,
                        binding.source_generation,
                        frame_index,
                    )
                    continue
                if (
                    not self._started
                    or self._bindings.get(binding.track_sid) is not binding
                    or binding.state not in {MediaSourceState.STARTED, MediaSourceState.ACTIVE}
                ):
                    continue
                self._publish_source_state(
                    binding, MediaSourceState.ACTIVE, reason="frame_received"
                )
                self._runtime.perception.publish_observation(observation)
        except asyncio.CancelledError:
            terminal_reason = "reader_cancelled"
            raise
        except Exception:
            terminal_state = MediaSourceState.ERROR
            terminal_reason = "reader_error"
            logger.exception(
                "LiveKit audio reader failed participant=%s track_sid=%s generation=%s",
                binding.transport_participant_id,
                binding.track_sid,
                binding.source_generation,
            )
        finally:
            if self._detach_binding(binding, state=terminal_state, reason=terminal_reason):
                await self._close_stream(binding)

    def _create_stream(
        self,
        *,
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        transport_participant_id: str,
    ) -> None:
        if not self._started:
            return
        existing = self._bindings.get(publication.sid)
        if existing is not None:
            if existing.publication is publication:
                return
            if self._detach_binding(
                existing, state=MediaSourceState.ENDED, reason="track_replaced"
            ):
                self._schedule_close(existing)

        source_id = self._source_id(
            transport_participant_id,
            publication.sid,
            int(publication.source),
        )
        binding = _AudioTrackBinding(
            track_sid=publication.sid,
            track_name=publication.name,
            track_source=int(publication.source),
            source=self._runtime.perception.next_source(source_id),
            transport_participant_id=transport_participant_id,
            publication=publication,
            stream=rtc.AudioStream(
                track,
                sample_rate=self._sample_rate,
                num_channels=self._num_channels,
                frame_size_ms=self._frame_size_ms,
            ),
        )
        self._bindings[binding.track_sid] = binding
        self._publish_source_state(
            binding,
            MediaSourceState.MUTED if publication.muted else MediaSourceState.STARTED,
            reason="track_subscribed",
        )
        binding.reader_task = self._spawn(
            self._read_stream(binding),
            name=f"livekit_audio_reader:{binding.track_sid}:{binding.source_generation}",
        )

    async def _close_stream(self, binding: _AudioTrackBinding) -> None:
        try:
            await binding.stream.aclose()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to close LiveKit audio stream participant=%s track_sid=%s generation=%s",
                binding.transport_participant_id,
                binding.track_sid,
                binding.source_generation,
            )

    async def _close_binding(self, binding: _AudioTrackBinding) -> None:
        await self._close_stream(binding)
        task = binding.reader_task
        if task is not None and task is not asyncio.current_task() and not task.done():
            await asyncio.gather(task, return_exceptions=True)

    def _attach_existing_tracks(self) -> None:
        for participant in self._room.remote_participants.values():
            for publication in participant.track_publications.values():
                track = publication.track
                if track is not None and publication.kind == rtc.TrackKind.KIND_AUDIO:
                    self._create_stream(
                        track=track,
                        publication=publication,
                        transport_participant_id=participant.identity,
                    )

    def _register_listeners(self) -> None:
        if self._listeners_registered:
            return
        self._listeners_registered = True

        @self._room.on("track_subscribed")
        def on_track_subscribed(
            track: rtc.Track,
            publication: rtc.RemoteTrackPublication,
            participant: rtc.RemoteParticipant,
        ) -> None:
            if self._started and track.kind == rtc.TrackKind.KIND_AUDIO:
                self._create_stream(
                    track=track,
                    publication=publication,
                    transport_participant_id=participant.identity,
                )

        @self._room.on("track_muted")
        def on_track_muted(
            publication: rtc.RemoteTrackPublication,
            participant: rtc.RemoteParticipant,
        ) -> None:
            if publication.kind == rtc.TrackKind.KIND_AUDIO and (
                binding := self._binding_for_publication(publication)
            ):
                self._publish_source_state(binding, MediaSourceState.MUTED, reason="track_muted")

        @self._room.on("track_unmuted")
        def on_track_unmuted(
            publication: rtc.RemoteTrackPublication,
            participant: rtc.RemoteParticipant,
        ) -> None:
            if publication.kind == rtc.TrackKind.KIND_AUDIO and (
                binding := self._binding_for_publication(publication)
            ):
                self._publish_source_state(
                    binding, MediaSourceState.STARTED, reason="track_unmuted"
                )

        @self._room.on("track_unsubscribed")
        def on_track_unsubscribed(
            track: rtc.Track,
            publication: rtc.RemoteTrackPublication,
            participant: rtc.RemoteParticipant,
        ) -> None:
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                self._schedule_close(
                    self._detach_publication(
                        publication,
                        state=MediaSourceState.ENDED,
                        reason="track_unsubscribed",
                    )
                )

        @self._room.on("track_unpublished")
        def on_track_unpublished(
            publication: rtc.RemoteTrackPublication,
            participant: rtc.RemoteParticipant,
        ) -> None:
            if publication.kind == rtc.TrackKind.KIND_AUDIO:
                self._schedule_close(
                    self._detach_publication(
                        publication,
                        state=MediaSourceState.ENDED,
                        reason="track_unpublished",
                    )
                )

        @self._room.on("participant_disconnected")
        def on_participant_disconnected(participant: rtc.RemoteParticipant) -> None:
            bindings = [
                binding
                for binding in self._bindings.values()
                if binding.transport_participant_id == participant.identity
            ]
            for binding in bindings:
                if self._detach_binding(
                    binding,
                    state=MediaSourceState.ENDED,
                    reason="participant_disconnected",
                ):
                    self._schedule_close(binding)

    async def on_session_start(self) -> None:
        if self._started:
            return

        self._started = True
        self._register_listeners()
        self._attach_existing_tracks()
        logger.info(
            "LiveKit audio input runtime started session_id=%s sample_rate=%s channels=%s",
            self._runtime.session.session_id,
            self._sample_rate,
            self._num_channels,
        )

    async def on_session_stop(self) -> None:
        if not self._started:
            return

        self._started = False
        bindings = list(self._bindings.values())
        for binding in bindings:
            self._detach_binding(binding, state=MediaSourceState.ENDED, reason="session_stopped")
        if bindings:
            await asyncio.gather(
                *(self._close_binding(binding) for binding in bindings), return_exceptions=True
            )
        tasks = list(self._tasks)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._bindings.clear()
        self._tasks.clear()
        logger.info(
            "LiveKit audio input runtime stopped session_id=%s",
            self._runtime.session.session_id,
        )
