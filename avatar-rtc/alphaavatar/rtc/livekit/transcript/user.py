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
import hashlib
import json
import logging
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from typing import Any

from livekit import rtc

from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.env.enums import ObservationKind
from alphaavatar.core.env.schemas import PerceptionSegmentRef, PerceptionSourceRef
from alphaavatar.core.lifecycle import LifecycleComponent
from alphaavatar.core.media import TextPayload
from alphaavatar.core.perception import PerceptionRuntime
from alphaavatar.core.perception.enums import MediaModality, MediaSourceKind, MediaSourceState

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _UserTranscript:
    segment: PerceptionSegmentRef
    input_source: PerceptionSourceRef
    participant_identity: str
    track_sid: str
    segment_id: str
    text: str
    language: str
    size: int
    queued_at: float


class LiveKitUserTranscriptOutput(LifecycleComponent):
    """Forward final STT observations, independently of Turn admission and assistant output."""

    def __init__(
        self,
        *,
        room: rtc.Room,
        perception: PerceptionRuntime,
        participant_identities: frozenset[str],
        consumer_id: str = "livekit:user_transcript",
        publish_legacy: bool = True,
        publish_text_stream: bool = True,
        publish_timeout: float = 5.0,
        max_pending_segments: int = 32,
        max_text_bytes: int = 65_536,
        max_pending_bytes: int = 262_144,
        max_queue_age: float = 30.0,
    ) -> None:
        if isinstance(participant_identities, str) or not participant_identities:
            raise ValueError("User transcript participants must be an explicit nonempty collection")
        participants = frozenset(participant_identities)
        if any(not isinstance(value, str) or not value for value in participants):
            raise ValueError("User transcript participant identities must be nonempty strings")
        if not consumer_id or not (publish_legacy or publish_text_stream):
            raise ValueError("User transcript requires a consumer identity and an enabled protocol")
        if (
            any(
                type(value) is not int or value <= 0
                for value in (max_pending_segments, max_text_bytes, max_pending_bytes)
            )
            or max_text_bytes > max_pending_bytes
        ):
            raise ValueError("User transcript capacities must be positive and consistent")
        if not all(isfinite(value) and value > 0 for value in (publish_timeout, max_queue_age)):
            raise ValueError("User transcript timeouts must be positive and finite")

        self._room, self._perception, self._participants = room, perception, participants
        self._name = consumer_id
        self._legacy, self._text_stream = publish_legacy, publish_text_stream
        self._timeout, self._max_age = publish_timeout, max_queue_age
        self._max_text_bytes, self._max_bytes = max_text_bytes, max_pending_bytes
        self._queue: asyncio.Queue[_UserTranscript] = asyncio.Queue(max_pending_segments)
        self._pending_bytes = 0
        self._recent: OrderedDict[str, bytes] = OrderedDict()
        self._tasks: list[asyncio.Task[None]] = []
        self._close_task: asyncio.Task[None] | None = None
        self._failed = asyncio.Event()
        self._error: BaseException | None = None
        self._cleanup_errors: list[Exception] = []
        self._started = False
        self._started_ns = 0

    @staticmethod
    def _input_source(observation: EnvObservation) -> PerceptionSourceRef | None:
        value = observation.metadata.get("input_source")
        if not isinstance(value, Mapping):
            return None
        source_id, generation = value.get("source_id"), value.get("source_generation")
        if not isinstance(source_id, str) or not source_id:
            return None
        if type(generation) is not int or generation <= 0:
            return None
        return PerceptionSourceRef(source_id=source_id, source_generation=generation)

    def _track_sid(self, source: PerceptionSourceRef, participant_identity: str) -> str | None:
        if participant_identity not in self._participants:
            return None
        participant = self._room.remote_participants.get(participant_identity)
        if participant is None:
            return None
        # Resolve the original capture binding, never parse Router's derived source names.
        for state in self._perception.get_source_states(
            modality=MediaModality.AUDIO, source_kind=MediaSourceKind.MICROPHONE
        ):
            if state.source != source or state.transport_participant_id != participant_identity:
                continue
            if (
                state.state
                not in {MediaSourceState.STARTED, MediaSourceState.ACTIVE, MediaSourceState.MUTED}
                or state.metadata.get("rtc_backend") != "livekit"
            ):
                return None
            sid = state.metadata.get("track_sid")
            if not isinstance(sid, str) or not sid:
                return None
            publication = participant.track_publications.get(sid)
            if (
                publication is not None
                and publication.kind == rtc.TrackKind.KIND_AUDIO
                and publication.track is not None
            ):
                return sid
        return None

    def _segment_id(self, participant: str, segment: PerceptionSegmentRef) -> str:
        identity = json.dumps(
            (self._perception.session_id, participant, segment.to_dict()),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return "SG_user_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def _remember(self, segment_id: str, digest: bytes) -> None:
        self._recent[segment_id] = digest
        self._recent.move_to_end(segment_id)
        while len(self._recent) > 1024:
            self._recent.popitem(last=False)

    def _ingest(self, observation: EnvObservation) -> None:
        if self._close_task is not None or observation.kind != ObservationKind.TRANSCRIPT_SEGMENT:
            return
        participant, segment = observation.transport_participant_id, observation.segment
        if (
            not isinstance(participant, str)
            or participant not in self._participants
            or segment is None
        ):
            return
        if observation.time_range.end.monotonic_ns < self._started_ns:
            return
        payload = observation.payload
        if not isinstance(payload, TextPayload) or not payload.text.strip():
            return
        source = self._input_source(observation)
        if source is None or (sid := self._track_sid(source, participant)) is None:
            logger.debug("USER TRANSCRIPT SKIPPED reason=missing_or_retired_audio_binding")
            return
        text = payload.text
        if len(text) > self._max_text_bytes:
            logger.warning("USER TRANSCRIPT DROPPED reason=text_capacity")
            return
        try:
            encoded = text.encode("utf-8")
        except UnicodeEncodeError:
            logger.warning("USER TRANSCRIPT DROPPED reason=invalid_utf8")
            return
        segment_id = self._segment_id(participant, segment)
        digest = hashlib.sha256(encoded).digest()
        if (previous := self._recent.get(segment_id)) is not None:
            if previous != digest:
                logger.warning(
                    "USER TRANSCRIPT DROPPED reason=conflicting_final segment=%s", segment_id
                )
            return
        # Remember attempts, not acknowledgements: ambiguous network delivery is never replayed.
        self._remember(segment_id, digest)
        size = len(encoded)
        if (
            size > self._max_text_bytes
            or self._pending_bytes + size > self._max_bytes
            or self._queue.full()
        ):
            logger.warning("USER TRANSCRIPT DROPPED reason=queue_capacity segment=%s", segment_id)
            return
        language = observation.metadata.get("language")
        if not isinstance(language, str) or len(language) > 64:
            language = ""
        self._queue.put_nowait(
            _UserTranscript(
                segment=segment,
                input_source=source,
                participant_identity=participant,
                track_sid=sid,
                segment_id=segment_id,
                text=text,
                language=language,
                size=size,
                queued_at=asyncio.get_running_loop().time(),
            )
        )
        self._pending_bytes += size

    async def _consume(self) -> None:
        stream = self._perception.text
        while True:
            await stream.wait_for_pending(consumer_id=self._name)
            window = stream.read_pending(consumer_id=self._name, limit=64)
            if window.has_gap:
                logger.warning("USER TRANSCRIPT GAP missed=%s", window.missed_count)
            for observation in window.items:
                self._ingest(observation)
            stream.commit(consumer_id=self._name, cursor_seq=window.cursor_seq)
            # A perpetually busy producer must not starve the independent sender or media tasks.
            await asyncio.sleep(0)

    def _current(self, item: _UserTranscript) -> bool:
        return (
            self._close_task is None
            and asyncio.get_running_loop().time() - item.queued_at <= self._max_age
            and self._track_sid(item.input_source, item.participant_identity) == item.track_sid
        )

    def _attributes(self, item: _UserTranscript, *, final: bool) -> dict[str, str]:
        return {
            "lk.segment_id": item.segment_id,
            "lk.transcribed_track_id": item.track_sid,
            "lk.transcription_final": str(final).lower(),
            "alphaavatar.type": "user_transcript",
            "alphaavatar.delivery": "recognized",
            "alphaavatar.session_id": self._perception.session_id,
            "alphaavatar.segment_id": item.segment.segment_id,
            "alphaavatar.source_id": item.segment.source.source_id,
            "alphaavatar.source_generation": str(item.segment.source.source_generation),
        }

    async def _send_text(self, item: _UserTranscript) -> None:
        writer: Any = None
        complete = False
        failure: BaseException | None = None

        async def open_writer() -> None:
            nonlocal writer
            async with asyncio.timeout(self._timeout):
                writer = await self._room.local_participant.stream_text(
                    topic="lk.transcription",
                    sender_identity=item.participant_identity,
                    attributes=self._attributes(item, final=False),
                )

        async def close_writer() -> None:
            async with asyncio.timeout(self._timeout):
                await writer.aclose(attributes=self._attributes(item, final=complete))

        try:
            # If opening settles after cancellation, its writer still has exactly one owner.
            await wait_for_cleanup(asyncio.create_task(open_writer(), name="user_transcript_open"))
            if not self._current(item):
                return
            async with asyncio.timeout(self._timeout):
                await writer.write(item.text)
            complete = self._current(item)
        except BaseException as error:
            failure = error
            raise
        finally:
            if writer is not None:
                try:
                    await wait_for_cleanup(
                        asyncio.create_task(close_writer(), name="user_transcript_writer_close")
                    )
                except BaseException as cleanup:
                    problem = cleanup
                    if isinstance(cleanup, asyncio.CancelledError):
                        problem = cleanup.__cause__
                    if self._close_task is not None and isinstance(problem, Exception):
                        self._cleanup_errors.append(problem)
                    if failure is not None:
                        raise failure from cleanup
                    raise

    async def _send_legacy(self, item: _UserTranscript) -> None:
        async with asyncio.timeout(self._timeout):
            await self._room.local_participant.publish_transcription(
                rtc.Transcription(
                    participant_identity=item.participant_identity,
                    track_sid=item.track_sid,
                    segments=[
                        rtc.TranscriptionSegment(
                            id=item.segment_id,
                            text=item.text,
                            start_time=0,
                            end_time=0,
                            final=True,
                            language=item.language,
                        )
                    ],
                )
            )

    async def _send(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                delivered = []
                for enabled, protocol, operation in (
                    (self._text_stream, "text_stream", self._send_text),
                    (self._legacy, "legacy", self._send_legacy),
                ):
                    if not enabled or not self._current(item):
                        continue
                    try:
                        await operation(item)
                        if self._current(item):
                            delivered.append(protocol)
                    except asyncio.CancelledError:
                        raise
                    except Exception as error:
                        logger.warning(
                            "USER TRANSCRIPT FAILED segment=%s protocol=%s error_type=%s",
                            item.segment_id,
                            protocol,
                            type(error).__name__,
                        )
                if delivered:
                    logger.info(
                        "USER TRANSCRIPT SENT session_id=%s segment=%s track_sid=%s "
                        "text_chars=%d protocols=%s stage=local_transport",
                        self._perception.session_id,
                        item.segment_id,
                        item.track_sid,
                        len(item.text),
                        ",".join(delivered),
                    )
                elif not self._current(item):
                    logger.debug(
                        "USER TRANSCRIPT SKIPPED reason=retired_or_expired segment=%s",
                        item.segment_id,
                    )
            finally:
                self._pending_bytes -= item.size
                self._queue.task_done()

    def _observe_worker(self, task: asyncio.Task[None]) -> None:
        if self._close_task is not None:
            return
        error = (
            RuntimeError("User transcript worker cancelled unexpectedly")
            if task.cancelled()
            else task.exception() or RuntimeError("User transcript worker exited unexpectedly")
        )
        self._error = error
        self._failed.set()
        logger.error("User transcript worker failed", exc_info=error)
        self._ensure_close()

    async def wait_failed(self) -> None:
        await self._failed.wait()
        raise RuntimeError("User transcript transport is unavailable") from self._error

    async def on_start(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("User transcript output is closing or closed")
        if self._started:
            return
        self._started_ns = self._perception.clock.now().monotonic_ns
        # New attachments do not replay the previous attachment's transcript history.
        stream = self._perception.text
        stream.commit(consumer_id=self._name, cursor_seq=stream.latest_seq)
        try:
            for worker, suffix in ((self._consume, "intake"), (self._send, "sender")):
                task = asyncio.create_task(worker(), name=f"{self._name}:{suffix}")
                self._tasks.append(task)
                task.add_done_callback(self._observe_worker)
            self._started = True
        except BaseException:
            await self.on_stop()
            raise

    async def _close(self) -> None:
        for task in self._tasks:
            if not task.done():
                task.cancel()
        results = await asyncio.gather(*self._tasks, return_exceptions=True)
        self._perception.text.clear_consumer(self._name)
        self._tasks.clear()
        while not self._queue.empty():
            self._queue.get_nowait()
            self._queue.task_done()
        self._pending_bytes = 0
        self._recent.clear()
        self._started = False
        errors = list(self._cleanup_errors)
        for error in results:
            if isinstance(error, Exception) and all(error is not value for value in errors):
                errors.append(error)
        if errors:
            raise ExceptionGroup("User transcript output cleanup failed", errors)

    @staticmethod
    def _observe_close(task: asyncio.Task[None]) -> None:
        if task.cancelled():
            logger.error("User transcript cleanup cancelled itself")
        elif (error := task.exception()) is not None:
            logger.error("User transcript cleanup failed", exc_info=error)

    def _ensure_close(self) -> asyncio.Task[None]:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="user_transcript_close")
            self._close_task.add_done_callback(self._observe_close)
        return self._close_task

    async def on_stop(self) -> None:
        await wait_for_cleanup(self._ensure_close())
