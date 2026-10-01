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
import logging
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any

from livekit import rtc

from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.env import EnvObservation, PerceptionSourceRef
from alphaavatar.core.media import AudioFramePayload
from alphaavatar.core.perception import (
    MediaModality,
    MediaSourceKind,
    MediaSourceState,
    MediaSourceStateEvent,
    PerceptionRuntime,
)
from alphaavatar.core.time import RuntimeTime, RuntimeTimeRange
from alphaavatar.rtc.livekit.utils.events import RoomEventBindings
from alphaavatar.rtc.livekit.utils.frame_id import create_frame_id

from .codec import from_livekit_audio_frame

logger = logging.getLogger(__name__)

AUDIO_STREAM_CLOSE_TIMEOUT_SEC = 2.0


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


class LiveKitAudioInput:
    """Translate LiveKit microphone tracks into audio observations and source-state events."""

    def __init__(
        self,
        *,
        room: rtc.Room,
        perception: PerceptionRuntime,
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
        self._perception = perception
        self._sample_rate = sample_rate
        self._num_channels = num_channels
        self._frame_size_ms = frame_size_ms

        self._bindings: dict[str, _AudioTrackBinding] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._reader_tasks: set[asyncio.Task[None]] = set()
        self._events = RoomEventBindings(room)
        self._stop_task: asyncio.Task[None] | None = None

        self._started = False

    @staticmethod
    def _source_id(
        participant_identity: str,
        track_sid: str,
        track_source: int,
    ) -> str:
        owner = participant_identity or "anonymous"
        discriminator = f"source:{track_source}" if track_source else f"track:{track_sid}"
        return f"env:audio:{owner}:{discriminator}"

    def _spawn(
        self, coroutine: Coroutine[Any, Any, None], *, name: str, reader: bool = False
    ) -> asyncio.Task[None]:
        task = asyncio.create_task(coroutine, name=name)
        self._tasks.add(task)
        if reader:
            self._reader_tasks.add(task)

        def on_done(completed: asyncio.Task[None]) -> None:
            self._tasks.discard(completed)
            self._reader_tasks.discard(completed)
            if completed.cancelled():
                return
            error = completed.exception()
            if error is not None:
                logger.error(
                    "%s background task failed task=%s",
                    type(self).__name__,
                    completed.get_name(),
                    exc_info=(type(error), error, error.__traceback__),
                )

        task.add_done_callback(on_done)
        return task

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
        self._perception.publish_source_state(
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
        self, publication: rtc.TrackPublication
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
        frame_id = create_frame_id(
            self._perception.session_id,
            binding.track_sid,
            binding.source_generation,
            frame_index,
            ended_at.unix_ns,
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
                ended_at = self._perception.clock.now()
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
                self._perception.publish_observation(observation)
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
            source=self._perception.next_source(source_id),
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
            reader=True,
        )

    async def _close_stream(self, binding: _AudioTrackBinding) -> None:
        await asyncio.wait_for(binding.stream.aclose(), timeout=AUDIO_STREAM_CLOSE_TIMEOUT_SEC)

    async def _close_binding(self, binding: _AudioTrackBinding) -> None:
        task = binding.reader_task
        try:
            if task is not None and task is not asyncio.current_task():
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        finally:
            await self._close_stream(binding)

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
        if self._events.registered:
            return

        self._listeners_registered = True

        @self._events.on("track_subscribed")
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

        @self._events.on("track_muted")
        def on_track_muted(
            participant: rtc.Participant,
            publication: rtc.TrackPublication,
        ) -> None:
            if not self._started or publication.kind != rtc.TrackKind.KIND_AUDIO:
                return
            if binding := self._binding_for_publication(publication):
                self._publish_source_state(binding, MediaSourceState.MUTED, reason="track_muted")

        @self._events.on("track_unmuted")
        def on_track_unmuted(
            participant: rtc.Participant,
            publication: rtc.TrackPublication,
        ) -> None:
            if not self._started or publication.kind != rtc.TrackKind.KIND_AUDIO:
                return
            if binding := self._binding_for_publication(publication):
                self._publish_source_state(
                    binding, MediaSourceState.STARTED, reason="track_unmuted"
                )

        @self._events.on("track_unsubscribed")
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

        @self._events.on("track_unpublished")
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

        @self._events.on("participant_disconnected")
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

    """Runtime operations"""

    async def _stop(self) -> None:
        errors: list[Exception] = []
        try:
            self._events.clear()
        except Exception as exc:
            errors.append(exc)

        bindings = tuple(self._bindings.values())
        self._bindings.clear()
        for binding in bindings:
            try:
                self._publish_source_state(
                    binding, MediaSourceState.ENDED, reason="session_stopped"
                )
            except Exception as exc:
                errors.append(exc)

        results = await asyncio.gather(
            *(self._close_binding(binding) for binding in bindings), return_exceptions=True
        )
        tasks = tuple(self._tasks)
        readers = set(self._reader_tasks)
        if tasks:
            pending_results = await asyncio.gather(*tasks, return_exceptions=True)
            results.extend(
                result
                for task, result in zip(tasks, pending_results, strict=True)
                if task not in readers or not isinstance(result, asyncio.CancelledError)
            )
        self._tasks.clear()
        self._reader_tasks.clear()

        for result in results:
            if isinstance(result, asyncio.CancelledError):
                error = RuntimeError(f"{type(self).__name__} cleanup task was cancelled")
                error.__cause__ = result
                errors.append(error)
            elif isinstance(result, Exception):
                errors.append(result)
            elif isinstance(result, BaseException):
                raise result

        if errors:
            raise ExceptionGroup(f"{type(self).__name__} cleanup failed", errors)
        logger.info("%s stopped session_id=%s", type(self).__name__, self._perception.session_id)

    async def on_session_start(self) -> None:
        if self._stop_task is not None:
            raise RuntimeError(f"{type(self).__name__} is closing or closed")
        if self._started:
            return

        self._started = True
        try:
            self._register_listeners()
            self._attach_existing_tracks()
        except BaseException:
            await self.on_session_stop()
            raise
        logger.info("%s started session_id=%s", type(self).__name__, self._perception.session_id)

    async def on_session_stop(self) -> None:
        if self._stop_task is None:
            self._started = False
            self._stop_task = asyncio.create_task(self._stop(), name=f"{type(self).__name__}:stop")
        await wait_for_cleanup(self._stop_task)
