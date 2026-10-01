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
from alphaavatar.core.media import VideoFramePayload
from alphaavatar.core.media.codecs.video import encode_video_frame_to_jpeg
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

from .codec import from_livekit_video_frame

logger = logging.getLogger(__name__)

VIDEO_STREAM_CLOSE_TIMEOUT_SEC = 2.0


@dataclass(slots=True)
class _VideoTrackBinding:
    track_sid: str
    track_name: str
    track_source: int

    source: PerceptionSourceRef
    source_kind: MediaSourceKind
    transport_participant_id: str

    publication: rtc.RemoteTrackPublication
    stream: rtc.VideoStream
    state: MediaSourceState | None = None
    reader_task: asyncio.Task[None] | None = None
    last_publish_monotonic_ns: int | None = None

    @property
    def source_id(self) -> str:
        return self.source.source_id

    @property
    def source_generation(self) -> int:
        return self.source.source_generation


class LiveKitVideoInput:
    """Translate LiveKit video tracks into video observations and source-state events."""

    def __init__(
        self,
        *,
        room: rtc.Room,
        perception: PerceptionRuntime,
        publish_interval_sec: float,
        jpeg_quality: int = 85,
    ) -> None:
        if publish_interval_sec <= 0:
            raise ValueError("publish_interval_sec must be positive")

        self._room = room
        self._perception = perception
        self._publish_interval_sec = publish_interval_sec
        self._jpeg_quality = jpeg_quality

        self._bindings: dict[str, _VideoTrackBinding] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._reader_tasks: set[asyncio.Task[None]] = set()
        self._events = RoomEventBindings(room)
        self._stop_task: asyncio.Task[None] | None = None

        self._started = False

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

    @staticmethod
    def _source_kind(publication: rtc.RemoteTrackPublication) -> MediaSourceKind:
        return (
            MediaSourceKind.SCREEN
            if publication.source == rtc.TrackSource.SOURCE_SCREENSHARE
            else MediaSourceKind.CAMERA
        )

    @staticmethod
    def _source_id(
        transport_participant_id: str,
        source_kind: MediaSourceKind,
        publication: rtc.RemoteTrackPublication,
    ) -> str:
        owner = transport_participant_id or "anonymous"

        # Standard LiveKit camera/screenshare publications represent one logical
        # source per participant. Re-publication becomes a new source generation.
        if publication.source in {
            rtc.TrackSource.SOURCE_CAMERA,
            rtc.TrackSource.SOURCE_SCREENSHARE,
        }:
            return f"env:{source_kind.value}:{owner}"

        # Unknown/custom tracks must remain independently addressable.
        return f"env:{source_kind.value}:{owner}:track:{publication.sid}"

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
        self._perception.publish_source_state(
            MediaSourceStateEvent(
                source=binding.source,
                modality=MediaModality.VIDEO,
                source_kind=binding.source_kind,
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
            "LiveKit video source state source_id=%s generation=%s state=%s reason=%s",
            binding.source_id,
            binding.source_generation,
            state.value,
            reason,
        )

    def _binding_for_publication(
        self, publication: rtc.TrackPublication
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
                name=f"livekit_video_close:{binding.track_sid}:{binding.source_generation}",
            )

    def _build_observation(
        self,
        *,
        binding: _VideoTrackBinding,
        frame: rtc.VideoFrame,
        frame_index: int,
        occurred_at: RuntimeTime,
    ) -> EnvObservation:
        frame_id = create_frame_id(
            self._perception.session_id,
            binding.track_sid,
            binding.source_generation,
            frame_index,
            occurred_at.unix_ns,
        )

        generic_frame = from_livekit_video_frame(frame)
        metadata: dict[str, Any] = {
            "track_sid": binding.track_sid,
            "track_name": binding.track_name,
            "track_source": binding.track_source,
            "frame_index": frame_index,
            "rtc_backend": "livekit",
        }

        payload = VideoFramePayload.create(
            frame=generic_frame,
            frame_id=frame_id,
            jpeg_bytes=encode_video_frame_to_jpeg(
                generic_frame,
                jpeg_quality=self._jpeg_quality,
            ),
            metadata=dict(metadata),
        )

        factory = (
            EnvObservation.screen_frame
            if binding.source_kind == MediaSourceKind.SCREEN
            else EnvObservation.video_frame
        )

        return factory(
            time_range=RuntimeTimeRange.point(occurred_at),
            source=binding.source,
            frame_id=frame_id,
            transport_participant_id=binding.transport_participant_id,
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
                occurred_at = self._perception.clock.now()

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
                        "Failed to convert LiveKit video frame participant=%s "
                        "track_sid=%s generation=%s frame_index=%s",
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
                    binding,
                    MediaSourceState.ACTIVE,
                    reason="frame_received",
                )
                self._perception.publish_observation(observation)

        except asyncio.CancelledError:
            terminal_reason = "reader_cancelled"
            raise
        except Exception:
            terminal_state = MediaSourceState.ERROR
            terminal_reason = "reader_error"
            logger.exception(
                "LiveKit video reader failed participant=%s track_sid=%s generation=%s",
                binding.transport_participant_id,
                binding.track_sid,
                binding.source_generation,
            )
        finally:
            if self._detach_binding(
                binding,
                state=terminal_state,
                reason=terminal_reason,
            ):
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
                existing,
                state=MediaSourceState.ENDED,
                reason="track_replaced",
            ):
                self._schedule_close(existing)

        source_kind = self._source_kind(publication)
        source_id = self._source_id(
            transport_participant_id,
            source_kind,
            publication,
        )

        binding = _VideoTrackBinding(
            track_sid=publication.sid,
            track_name=publication.name,
            track_source=int(publication.source),
            source=self._perception.next_source(source_id),
            source_kind=source_kind,
            transport_participant_id=transport_participant_id,
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
            name=f"livekit_video_reader:{binding.track_sid}:{binding.source_generation}",
            reader=True,
        )

    async def _close_stream(self, binding: _VideoTrackBinding) -> None:
        await asyncio.wait_for(binding.stream.aclose(), timeout=VIDEO_STREAM_CLOSE_TIMEOUT_SEC)

    async def _close_binding(self, binding: _VideoTrackBinding) -> None:
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
                if track is not None and publication.kind == rtc.TrackKind.KIND_VIDEO:
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
            if self._started and track.kind == rtc.TrackKind.KIND_VIDEO:
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
            if not self._started or publication.kind != rtc.TrackKind.KIND_VIDEO:
                return
            if binding := self._binding_for_publication(publication):
                self._publish_source_state(binding, MediaSourceState.MUTED, reason="track_muted")

        @self._events.on("track_unmuted")
        def on_track_unmuted(
            participant: rtc.Participant,
            publication: rtc.TrackPublication,
        ) -> None:
            if not self._started or publication.kind != rtc.TrackKind.KIND_VIDEO:
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
            if track.kind == rtc.TrackKind.KIND_VIDEO:
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
            if publication.kind == rtc.TrackKind.KIND_VIDEO:
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
