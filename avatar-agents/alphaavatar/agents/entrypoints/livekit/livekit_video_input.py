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
from alphaavatar.agents.plugin import AvatarRuntimePlugin
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.utils.id_utils import get_md5_id
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.media import VideoFramePayload
from alphaavatar.core.perception import (
    MediaModality,
    MediaSourceKind,
    MediaSourceState,
    MediaSourceStateEvent,
)
from alphaavatar.core.time import RuntimeTime, RuntimeTimeRange
from livekit import rtc

from .livekit_video_codec import encode_video_frame_to_jpeg, from_livekit_video_frame

VIDEO_READER_STOP_TIMEOUT_SEC = 1.0
VIDEO_STREAM_CLOSE_TIMEOUT_SEC = 2.0
VIDEO_TASK_DRAIN_TIMEOUT_SEC = 2.0


@dataclass(slots=True)
class _VideoTrackBinding:
    track_sid: str
    track_name: str
    track_source: int
    participant_identity: str
    source_id: str
    source_kind: MediaSourceKind
    generation: int
    publication: rtc.RemoteTrackPublication
    stream: rtc.VideoStream
    state: MediaSourceState | None = None
    reader_task: asyncio.Task[None] | None = None
    last_publish_monotonic_ns: int | None = None


class LiveKitVideoInput(AvatarRuntimePlugin):
    """Translate LiveKit video tracks into AlphaAvatar observations and source-state events."""

    def __init__(
        self,
        *,
        room: rtc.Room,
        runtime: AvatarRuntime,
        publish_interval_sec: float,
        jpeg_quality: int = 85,
    ) -> None:
        if publish_interval_sec <= 0:
            raise ValueError("publish_interval_sec must be positive")

        self._room = room
        self._runtime = runtime
        self._publish_interval_sec = publish_interval_sec
        self._jpeg_quality = jpeg_quality
        self._bindings: dict[str, _VideoTrackBinding] = {}
        self._generation_by_source: dict[str, int] = {}
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
                    "LiveKit video background task failed task=%s",
                    completed.get_name(),
                    exc_info=(type(error), error, error.__traceback__),
                )

        task.add_done_callback(on_done)
        return task

    @staticmethod
    def _source_kind(publication: rtc.RemoteTrackPublication) -> MediaSourceKind:
        return (
            MediaSourceKind.SCREEN
            if publication.source == rtc.TrackSource.SOURCE_SCREENSHARE
            else MediaSourceKind.CAMERA
        )

    @staticmethod
    def _source_id(participant_identity: str, source_kind: MediaSourceKind, track_sid: str) -> str:
        identity = participant_identity or track_sid
        return f"env:{source_kind.value}:{identity}"

    def _next_generation(self, source_id: str) -> int:
        generation = self._generation_by_source.get(source_id, 0) + 1
        self._generation_by_source[source_id] = generation
        return generation

    def _publish_source_state(
        self,
        binding: _VideoTrackBinding,
        state: MediaSourceState,
        *,
        reason: str,
    ) -> None:
        if binding.state == state:
            return
        binding.state = state
        self._runtime.perception.publish_source_state(
            MediaSourceStateEvent(
                source_id=binding.source_id,
                generation=binding.generation,
                modality=MediaModality.VIDEO,
                source_kind=binding.source_kind,
                state=state,
                reason=reason,
                metadata={
                    "rtc_backend": "livekit",
                    "track_sid": binding.track_sid,
                    "track_name": binding.track_name,
                    "track_source": binding.track_source,
                    "participant_identity": binding.participant_identity,
                },
            )
        )
        logger.info(
            "LiveKit video source state source_id=%s generation=%s state=%s reason=%s",
            binding.source_id,
            binding.generation,
            state.value,
            reason,
        )

    def _binding_for_publication(
        self,
        publication: rtc.RemoteTrackPublication,
    ) -> _VideoTrackBinding | None:
        binding = self._bindings.get(publication.sid)
        return binding if binding is not None and binding.publication is publication else None

    def _detach_binding(
        self,
        binding: _VideoTrackBinding,
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
    ) -> _VideoTrackBinding | None:
        binding = self._binding_for_publication(publication)
        return (
            binding
            if binding and self._detach_binding(binding, state=state, reason=reason)
            else None
        )

    def _schedule_close(self, binding: _VideoTrackBinding | None) -> None:
        if binding is not None:
            self._spawn(
                self._close_binding(binding),
                name=f"livekit_video_close:{binding.track_sid}:{binding.generation}",
            )

    def _build_observation(
        self,
        *,
        binding: _VideoTrackBinding,
        frame: rtc.VideoFrame,
        frame_index: int,
        occurred_at: RuntimeTime,
    ) -> EnvObservation:
        frame_id = get_md5_id(
            [
                self._runtime.session.session_id,
                binding.track_sid,
                str(binding.generation),
                str(frame_index),
                str(occurred_at.unix_ns),
            ]
        )
        generic_frame = from_livekit_video_frame(frame)
        metadata: dict[str, Any] = {
            "frame_id": frame_id,
            "track_sid": binding.track_sid,
            "track_name": binding.track_name,
            "track_source": binding.track_source,
            "participant_identity": binding.participant_identity,
            "source_generation": binding.generation,
            "source_kind": binding.source_kind.value,
            "frame_index": frame_index,
            "rtc_backend": "livekit",
        }
        payload = VideoFramePayload.create(
            frame=generic_frame,
            frame_id=frame_id,
            jpeg_bytes=encode_video_frame_to_jpeg(generic_frame, jpeg_quality=self._jpeg_quality),
            metadata=dict(metadata),
        )
        factory = (
            EnvObservation.screen_frame
            if binding.source_kind == MediaSourceKind.SCREEN
            else EnvObservation.video_frame
        )
        return factory(
            time_range=RuntimeTimeRange.point(occurred_at),
            source_id=binding.source_id,
            payload=payload,
            metadata=metadata,
        )

    def _should_publish(self, binding: _VideoTrackBinding, occurred_at: RuntimeTime) -> bool:
        last = binding.last_publish_monotonic_ns
        if (
            last is not None
            and (occurred_at.monotonic_ns - last) / 1_000_000_000 < self._publish_interval_sec
        ):
            return False
        binding.last_publish_monotonic_ns = occurred_at.monotonic_ns
        return True

    async def _read_stream(self, binding: _VideoTrackBinding) -> None:
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
                occurred_at = self._runtime.clock.now()
                if not self._should_publish(binding, occurred_at):
                    continue
                try:
                    observation = await asyncio.to_thread(
                        self._build_observation,
                        binding=binding,
                        frame=event.frame,
                        frame_index=frame_index,
                        occurred_at=occurred_at,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Failed to convert LiveKit video frame participant=%s track_sid=%s generation=%s frame_index=%s",
                        binding.participant_identity,
                        binding.track_sid,
                        binding.generation,
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
                "LiveKit video reader failed participant=%s track_sid=%s generation=%s",
                binding.participant_identity,
                binding.track_sid,
                binding.generation,
            )
        finally:
            if self._detach_binding(binding, state=terminal_state, reason=terminal_reason):
                await self._close_stream(binding)

    def _create_stream(
        self,
        *,
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant_identity: str,
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

        source_kind = self._source_kind(publication)
        source_id = self._source_id(participant_identity, source_kind, publication.sid)
        binding = _VideoTrackBinding(
            track_sid=publication.sid,
            track_name=publication.name,
            track_source=int(publication.source),
            participant_identity=participant_identity,
            source_id=source_id,
            source_kind=source_kind,
            generation=self._next_generation(source_id),
            publication=publication,
            stream=rtc.VideoStream(track),
        )
        self._bindings[binding.track_sid] = binding
        self._publish_source_state(
            binding,
            MediaSourceState.MUTED if publication.muted else MediaSourceState.STARTED,
            reason="track_subscribed",
        )
        binding.reader_task = self._spawn(
            self._read_stream(binding),
            name=f"livekit_video_reader:{binding.track_sid}:{binding.generation}",
        )

    async def _close_stream(self, binding: _VideoTrackBinding) -> None:
        try:
            await asyncio.wait_for(
                binding.stream.aclose(),
                timeout=VIDEO_STREAM_CLOSE_TIMEOUT_SEC,
            )
        except TimeoutError:
            logger.warning(
                "Timed out closing LiveKit video stream track_sid=%s generation=%s",
                binding.track_sid,
                binding.generation,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to close LiveKit video stream track_sid=%s generation=%s",
                binding.track_sid,
                binding.generation,
            )

    async def _close_binding(self, binding: _VideoTrackBinding) -> None:
        reader_task = binding.reader_task

        if (
            reader_task is not None
            and reader_task is not asyncio.current_task()
            and not reader_task.done()
        ):
            reader_task.cancel()

            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        reader_task,
                        return_exceptions=True,
                    ),
                    timeout=VIDEO_READER_STOP_TIMEOUT_SEC,
                )
            except TimeoutError:
                logger.warning(
                    "Timed out stopping LiveKit video reader track_sid=%s generation=%s",
                    binding.track_sid,
                    binding.generation,
                )

        await self._close_stream(binding)

    def _attach_existing_tracks(self) -> None:
        for participant in self._room.remote_participants.values():
            for publication in participant.track_publications.values():
                track = publication.track
                if track is not None and publication.kind == rtc.TrackKind.KIND_VIDEO:
                    self._create_stream(
                        track=track,
                        publication=publication,
                        participant_identity=participant.identity,
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
            if self._started and track.kind == rtc.TrackKind.KIND_VIDEO:
                self._create_stream(
                    track=track,
                    publication=publication,
                    participant_identity=participant.identity,
                )

        @self._room.on("track_muted")
        def on_track_muted(
            publication: rtc.RemoteTrackPublication,
            participant: rtc.RemoteParticipant,
        ) -> None:
            if publication.kind == rtc.TrackKind.KIND_VIDEO and (
                binding := self._binding_for_publication(publication)
            ):
                self._publish_source_state(binding, MediaSourceState.MUTED, reason="track_muted")

        @self._room.on("track_unmuted")
        def on_track_unmuted(
            publication: rtc.RemoteTrackPublication,
            participant: rtc.RemoteParticipant,
        ) -> None:
            if publication.kind == rtc.TrackKind.KIND_VIDEO and (
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
            if track.kind == rtc.TrackKind.KIND_VIDEO:
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
            if publication.kind == rtc.TrackKind.KIND_VIDEO:
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
                if binding.participant_identity == participant.identity
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
            "LiveKit video input runtime started session_id=%s sample_interval=%ss",
            self._runtime.session.session_id,
            self._publish_interval_sec,
        )

    async def on_session_stop(self) -> None:
        if not self._started:
            return

        self._started = False

        logger.debug(
            "Stopping LiveKit video input runtime session_id=%s bindings=%s tasks=%s",
            self._runtime.session.session_id,
            len(self._bindings),
            len(self._tasks),
        )

        bindings: list[_VideoTrackBinding] = []

        for binding in tuple(self._bindings.values()):
            if self._detach_binding(
                binding,
                state=MediaSourceState.ENDED,
                reason="session_stopped",
            ):
                bindings.append(binding)

        if bindings:
            await asyncio.gather(
                *(self._close_binding(binding) for binding in bindings),
                return_exceptions=True,
            )

        remaining_tasks = [task for task in self._tasks if not task.done()]

        if remaining_tasks:
            _, pending = await asyncio.wait(
                remaining_tasks,
                timeout=VIDEO_TASK_DRAIN_TIMEOUT_SEC,
            )

            for task in pending:
                task.cancel()

            if pending:
                await asyncio.gather(
                    *pending,
                    return_exceptions=True,
                )

        self._bindings.clear()
        self._generation_by_source.clear()
        self._tasks.clear()

        logger.info(
            "LiveKit video input runtime stopped session_id=%s",
            self._runtime.session.session_id,
        )
