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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from alphaavatar.agents.memory import MemoryContextState
from alphaavatar.core.env import EnvObservation, ObservationKind
from alphaavatar.core.perception import (
    AlignedPerception,
    PerceptionCutoff,
    PerceptionEvent,
    PerceptionRuntime,
    PerceptionTemporalAligner,
    TemporalAlignmentMode,
    TemporalAlignmentPolicy,
)
from alphaavatar.core.time import RuntimeTimeRange

from ...log import logger
from .input_builder import EnvMemoryInput, EnvMemoryInputBuilder

DEFAULT_ENV_MEMORY_INTERVAL_SEC = 30.0
DEFAULT_ANNOTATION_GRACE_SEC = 0.75
DEFAULT_MAX_SPEECH_DEFER_SEC = 15.0

DEFAULT_PROCESS_TIMEOUT_SEC = 45.0
DEFAULT_SHUTDOWN_PROCESS_TIMEOUT_SEC = 8.0

DEFAULT_RETRY_DELAY_SEC = 0.5
DEFAULT_MAX_ATTEMPTS = 2


@dataclass(slots=True)
class EnvMemoryBatch:
    context_id: str
    from_sequence: int
    to_sequence: int
    events: tuple[PerceptionEvent, ...]
    alignment: AlignedPerception
    memory_input: EnvMemoryInput
    chat_context: str | None
    triggers: set[str] = field(default_factory=set)
    raw_event_count: int = 0
    message_count: int = 0
    attempts: int = 0

    @property
    def observations(self) -> list[EnvObservation]:
        return list(self.memory_input.observations)

    @property
    def conversation_context(self) -> str | None:
        return self.chat_context

    @property
    def trigger_text(self) -> str:
        return ",".join(sorted(self.triggers))

    @property
    def missed_count(self) -> int:
        return self.alignment.missed_event_count

    @property
    def raw_observation_count(self) -> int:
        return sum(event.observation is not None for event in self.events)

    def build_evidence(self) -> list[dict]:
        return list(self.memory_input.evidence)

    async def merge(
        self,
        other: EnvMemoryBatch,
        *,
        aligner: PerceptionTemporalAligner,
        input_builder: EnvMemoryInputBuilder,
    ) -> None:
        if self.context_id != other.context_id:
            raise ValueError("Cannot merge ENV memory batches from different contexts")

        self.from_sequence = min(self.from_sequence, other.from_sequence)
        self.to_sequence = max(self.to_sequence, other.to_sequence)
        self.attempts = 0

        by_sequence = {event.sequence: event for event in self.events}
        by_sequence.update({event.sequence: event for event in other.events})
        self.events = tuple(by_sequence[sequence] for sequence in sorted(by_sequence))

        start = min(
            self.alignment.time_range.start,
            other.alignment.time_range.start,
            key=lambda item: item.monotonic_ns,
        )
        end = max(
            self.alignment.time_range.end,
            other.alignment.time_range.end,
            key=lambda item: item.monotonic_ns,
        )
        self.alignment = aligner.align(
            events=self.events,
            time_range=RuntimeTimeRange(start=start, end=end),
            source_states_at_start=self.alignment.source_states_at_start,
            source_states_at_end=other.alignment.source_states_at_end,
            mode=TemporalAlignmentMode.FIXED,
            has_event_gap=self.alignment.has_event_gap or other.alignment.has_event_gap,
            missed_event_count=self.alignment.missed_event_count
            + other.alignment.missed_event_count,
        )
        self.memory_input = await asyncio.to_thread(
            input_builder.build,
            self.alignment,
        )

        contexts = [item for item in (self.chat_context, other.chat_context) if item]
        self.chat_context = "\n\n".join(dict.fromkeys(contexts)) if contexts else None
        self.triggers.update(other.triggers)
        self.raw_event_count += other.raw_event_count
        self.message_count += other.message_count


ProcessCallback = Callable[[EnvMemoryBatch, float], Awaitable[object]]
MessageRenderer = Callable[[list[Any]], str | None]


class EnvMemoryScheduler:
    CONSUMER_ID = "memory.env"

    _ENV_OBSERVATION_KINDS = {
        ObservationKind.VIDEO_FRAME,
        ObservationKind.SCREEN_FRAME,
        ObservationKind.VIDEO_CLIP,
        ObservationKind.AUDIO_FRAME,
        ObservationKind.AUDIO_SEGMENT,
    }

    def __init__(
        self,
        *,
        perception_runtime: PerceptionRuntime,
        context_state: MemoryContextState,
        initial_cutoff: PerceptionCutoff,
        process: ProcessCallback,
        render_messages: MessageRenderer,
        alignment_policy: TemporalAlignmentPolicy | None = None,
        include_audio: bool = True,
    ) -> None:
        policy = alignment_policy or TemporalAlignmentPolicy(mode=TemporalAlignmentMode.FIXED)

        self._perception_runtime = perception_runtime
        self._context_state = context_state
        self._process = process
        self._render_messages = render_messages
        self._include_audio = include_audio

        self._aligner = PerceptionTemporalAligner(policy)
        self._input_builder = EnvMemoryInputBuilder(include_audio=include_audio)
        self._last_cutoff = initial_cutoff

        perception_runtime.events.commit(
            consumer_id=self.CONSUMER_ID,
            cursor_seq=initial_cutoff.sequence,
        )

        self._requested_triggers: set[str] = set()
        self._wake_event = asyncio.Event()
        self._pending_batch: EnvMemoryBatch | None = None
        self._scheduler_task: asyncio.Task[None] | None = None
        self._processor_task: asyncio.Task[None] | None = None
        self._stopping = False

    @property
    def context_id(self) -> str:
        return self._context_state.context_id

    def _take_requested_triggers(self) -> set[str]:
        self._wake_event.clear()
        triggers = self._requested_triggers
        self._requested_triggers = set()
        return triggers

    def _environment_events(
        self,
        events: tuple[PerceptionEvent, ...],
    ) -> tuple[PerceptionEvent, ...]:
        return tuple(
            event
            for event in events
            if event.source_state is not None
            or (
                event.observation is not None
                and event.observation.kind in self._ENV_OBSERVATION_KINDS
                and event.observation.metadata.get("input_origin") != "direct_upload"
            )
        )

    async def _merge_pending_batch(self, batch: EnvMemoryBatch) -> None:
        if self._pending_batch is None:
            self._pending_batch = batch
            return

        await self._pending_batch.merge(
            batch,
            aligner=self._aligner,
            input_builder=self._input_builder,
        )

    async def _restore_pending_batch(self, batch: EnvMemoryBatch) -> None:
        if self._pending_batch is not None:
            await batch.merge(
                self._pending_batch,
                aligner=self._aligner,
                input_builder=self._input_builder,
            )
        self._pending_batch = batch

    async def _resolve_capture_cutoff(self, triggers: set[str]) -> PerceptionCutoff:
        """
        Resolve a semantic capture boundary.

        Normal triggers wait for an active VAD segment to close. Session shutdown
        is a hard boundary and never waits.
        """
        if (
            not self._include_audio
            or DEFAULT_MAX_SPEECH_DEFER_SEC == 0
            or "session_stop" in triggers
        ):
            return self._perception_runtime.capture_cutoff()

        cutoff = self._perception_runtime.capture_cutoff_if_speech_idle()
        if cutoff is not None:
            return cutoff

        started_at = asyncio.get_running_loop().time()

        cutoff = await self._perception_runtime.wait_for_speech_idle_cutoff(
            timeout=DEFAULT_MAX_SPEECH_DEFER_SEC,
        )
        if cutoff is not None:
            deferred_sec = asyncio.get_running_loop().time() - started_at
            triggers.add("speech_boundary")

            logger.debug(
                "[Memory] ENV capture deferred to speech boundary sid=%s deferred=%.2fs",
                self.context_id,
                deferred_sec,
            )
            return cutoff

        triggers.add("speech_defer_timeout")

        logger.warning(
            "[Memory] ENV speech-boundary wait timed out sid=%s timeout=%ss active_segments=%s",
            self.context_id,
            DEFAULT_MAX_SPEECH_DEFER_SEC,
            self._perception_runtime.active_speech_segments,
        )

        return self._perception_runtime.capture_cutoff()

    async def _capture_batch(
        self,
        triggers: set[str],
        *,
        target_cutoff: PerceptionCutoff,
    ) -> EnvMemoryBatch | None:
        start_cutoff = self._last_cutoff

        if target_cutoff.sequence <= start_cutoff.sequence:
            return None

        read = self._perception_runtime.events.read_range(
            after_seq=start_cutoff.sequence,
            until_seq=target_cutoff.sequence,
        )

        all_events = tuple(read.items)
        has_gap = read.has_gap
        missed_count = read.missed_count

        if has_gap:
            logger.warning(
                "[Memory] ENV event gap sid=%s triggers=%s missed=%s range=%s..%s",
                self.context_id,
                sorted(triggers),
                missed_count,
                start_cutoff.sequence,
                target_cutoff.sequence,
            )

        events = self._environment_events(all_events)
        start = start_cutoff.captured_at
        end = target_cutoff.captured_at

        if end.monotonic_ns < start.monotonic_ns:
            end = start

        alignment = self._aligner.align(
            events=events,
            time_range=RuntimeTimeRange(
                start=start,
                end=end,
            ),
            source_states_at_start=start_cutoff.sources,
            source_states_at_end=target_cutoff.sources,
            mode=TemporalAlignmentMode.FIXED,
            has_event_gap=has_gap,
            missed_event_count=missed_count,
        )

        memory_input = await asyncio.to_thread(
            self._input_builder.build,
            alignment,
        )

        self._perception_runtime.events.commit(
            consumer_id=self.CONSUMER_ID,
            cursor_seq=target_cutoff.sequence,
        )
        self._last_cutoff = target_cutoff

        messages = self._context_state.take_pending_env_messages()

        batch = EnvMemoryBatch(
            context_id=self.context_id,
            from_sequence=start_cutoff.sequence,
            to_sequence=target_cutoff.sequence,
            events=events,
            alignment=alignment,
            memory_input=memory_input,
            chat_context=self._render_messages(messages),
            triggers=set(triggers),
            raw_event_count=len(all_events),
            message_count=len(messages),
        )

        self._context_state.commit_env_messages()
        return batch

    async def _enqueue_batch(self, batch: EnvMemoryBatch) -> None:
        await self._merge_pending_batch(batch)

        if not self._stopping and (self._processor_task is None or self._processor_task.done()):
            self._processor_task = asyncio.create_task(
                self._processor_loop(),
                name=f"memory_env_processor:{self.context_id}",
            )

    async def _capture_and_enqueue(
        self,
        triggers: set[str],
        *,
        annotation_grace_sec: float | None = None,
    ) -> bool:
        if not triggers:
            return False

        try:
            target_cutoff = await self._resolve_capture_cutoff(triggers)

            grace_sec = (
                DEFAULT_ANNOTATION_GRACE_SEC
                if annotation_grace_sec is None
                else annotation_grace_sec
            )

            # Wait after freezing the cutoff. Annotations can settle, while events
            # published after target_cutoff remain outside this batch.
            if grace_sec > 0:
                await asyncio.sleep(grace_sec)

            batch = await self._capture_batch(
                triggers,
                target_cutoff=target_cutoff,
            )

            if batch is None:
                return False

            await self._enqueue_batch(batch)
            return True

        except asyncio.CancelledError:
            raise

        except Exception:
            logger.exception(
                "[Memory] ENV capture failed cid=%s triggers=%s",
                self.context_id,
                sorted(triggers),
            )
            return False

    async def _scheduler_loop(self) -> None:
        loop = asyncio.get_running_loop()
        next_periodic_at = loop.time() + DEFAULT_ENV_MEMORY_INTERVAL_SEC

        while True:
            try:
                timeout = max(0.0, next_periodic_at - loop.time())

                try:
                    await asyncio.wait_for(
                        self._wake_event.wait(),
                        timeout=timeout,
                    )

                except TimeoutError:
                    triggers = {"periodic"}
                    if self._wake_event.is_set():
                        triggers.update(self._take_requested_triggers())

                    await self._capture_and_enqueue(triggers)
                    next_periodic_at = loop.time() + DEFAULT_ENV_MEMORY_INTERVAL_SEC
                    continue

                captured = await self._capture_and_enqueue(self._take_requested_triggers())
                if captured:
                    next_periodic_at = loop.time() + DEFAULT_ENV_MEMORY_INTERVAL_SEC
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "[Memory] ENV scheduler failed cid=%s",
                    self.context_id,
                )
                await asyncio.sleep(0.05)

    async def _processor_loop(self) -> None:
        while self._pending_batch is not None:
            batch = self._pending_batch
            self._pending_batch = None

            try:
                while True:
                    try:
                        await self._process(batch, DEFAULT_PROCESS_TIMEOUT_SEC)
                        break
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        batch.attempts += 1

                        if batch.attempts >= DEFAULT_MAX_ATTEMPTS:
                            logger.exception(
                                "[Memory] ENV batch retained context=%s attempts=%s "
                                "triggers=%s events=%s",
                                batch.context_id,
                                batch.attempts,
                                sorted(batch.triggers),
                                len(batch.events),
                            )
                            await self._restore_pending_batch(batch)
                            return

                        logger.warning(
                            "[Memory] ENV processing failed; retrying context=%s attempt=%s",
                            batch.context_id,
                            batch.attempts,
                            exc_info=True,
                        )
                        await asyncio.sleep(DEFAULT_RETRY_DELAY_SEC)

            except asyncio.CancelledError:
                await self._restore_pending_batch(batch)
                raise

    def request(self, trigger: str) -> None:
        if self._stopping or not (trigger := trigger.strip()):
            return
        self._requested_triggers.add(trigger)
        self._wake_event.set()

    async def start(self) -> None:
        if self._scheduler_task is not None and not self._scheduler_task.done():
            return

        self._stopping = False
        self._scheduler_task = asyncio.create_task(
            self._scheduler_loop(),
            name=f"memory_env_scheduler:{self.context_id}",
        )

    async def stop(self) -> None:
        if self._stopping:
            return

        self._stopping = True

        logger.info(
            "[Memory] ENV scheduler stopping cid=%s",
            self.context_id,
        )

        if self._scheduler_task is not None:
            self._scheduler_task.cancel()
            await asyncio.gather(
                self._scheduler_task,
                return_exceptions=True,
            )
            self._scheduler_task = None

        # Cancel the active provider request. _processor_loop restores its current
        # batch to _pending_batch on cancellation.
        if self._processor_task is not None and not self._processor_task.done():
            self._processor_task.cancel()
            await asyncio.gather(
                self._processor_task,
                return_exceptions=True,
            )

        self._processor_task = None

        try:
            final_cutoff = self._perception_runtime.capture_cutoff()
            final_batch = await self._capture_batch(
                {"session_stop"},
                target_cutoff=final_cutoff,
            )

            if final_batch is not None:
                await self._merge_pending_batch(final_batch)

            batch = self._pending_batch
            self._pending_batch = None

            if batch is not None:
                try:
                    await asyncio.wait_for(
                        self._process(batch, DEFAULT_SHUTDOWN_PROCESS_TIMEOUT_SEC),
                        timeout=DEFAULT_SHUTDOWN_PROCESS_TIMEOUT_SEC + 1.0,
                    )
                except BaseException:
                    self._pending_batch = batch
                    raise

        finally:
            self._perception_runtime.events.clear_consumer(self.CONSUMER_ID)
            logger.info("[Memory] ENV scheduler stopped context=%s", self.context_id)
