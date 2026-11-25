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
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.perception import (
    PerceptionRuntime,
    PerceptionTemporalAligner,
    TemporalAlignmentMode,
    TemporalAlignmentPolicy,
)
from alphaavatar.core.perception.schemas import PerceptionCutoff

from ...state import MemoryContextState
from .batch import EnvironmentBatchError, EnvMemoryBatch, EnvMemoryBatchBuilder
from .config import EnvironmentSchedulerConfig
from .input_builder import EnvMemoryInputBuilder

logger = logging.getLogger(__name__)

DEFAULT_ENV_MEMORY_INTERVAL_SEC = 30.0
DEFAULT_ANNOTATION_GRACE_SEC = 0.75
DEFAULT_MAX_SPEECH_DEFER_SEC = 15.0
DEFAULT_RETRY_DELAY_SEC = 0.5

ProcessCallback = Callable[[EnvMemoryBatch, float], Awaitable[object]]
MessageRenderer = Callable[[list[Any]], str | None]


class EnvMemoryScheduler:
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
        config: EnvironmentSchedulerConfig | None = None,
    ) -> None:
        self._config = config or EnvironmentSchedulerConfig()
        self._perception_runtime, self._context_state = perception_runtime, context_state
        self._process, self._render_messages, self._include_audio = (
            process,
            render_messages,
            include_audio,
        )
        self._builder = EnvMemoryBatchBuilder(
            config=self._config,
            aligner=PerceptionTemporalAligner(
                alignment_policy or TemporalAlignmentPolicy(mode=TemporalAlignmentMode.FIXED)
            ),
            input_builder=EnvMemoryInputBuilder(include_audio=include_audio),
        )
        self._last_cutoff = initial_cutoff
        self._committed_sequence = initial_cutoff.sequence
        self._consumer_id = f"memory.environment:{context_state.context_id}"
        perception_runtime.events.commit(
            consumer_id=self._consumer_id, cursor_seq=initial_cutoff.sequence
        )
        self._pending_batches: deque[EnvMemoryBatch] = deque()
        self._active_batch: EnvMemoryBatch | None = None
        self._capture_lock = asyncio.Lock()
        self._requested_triggers: set[str] = set()
        self._wake_event = asyncio.Event()
        self._scheduler_task: asyncio.Task[None] | None = None
        self._processor_task: asyncio.Task[None] | None = None
        self._stop_task: asyncio.Task[None] | None = None
        self._stopping = False
        self._failure: str | None = None

    @property
    def context_id(self) -> str:
        return self._context_state.context_id

    @property
    def status(self) -> dict[str, Any]:
        batches = (*self._pending_batches, *((self._active_batch,) if self._active_batch else ()))
        latest = self._perception_runtime.capture_cutoff().sequence
        return {
            "context_id": self.context_id,
            "state": "failed" if self._failure else "stopped" if self._stopping else "running",
            "failure": self._failure,
            "pending_batches": len(self._pending_batches),
            "retained_events": sum(len(batch.events) for batch in batches),
            "retained_source_bytes": sum(batch.payload_bytes for batch in batches),
            "committed_sequence": self._committed_sequence,
            "captured_sequence": self._last_cutoff.sequence,
            "uncommitted_from_sequence": self._committed_sequence,
            "uncommitted_to_sequence": latest,
        }

    def _halt(self, reason: str) -> None:
        if self._failure is None:
            self._failure = reason
            logger.error("ENV processing halted reason=%s status=%s", reason, self.status)
        self._wake_event.set()

    def _take_requested_triggers(self) -> set[str]:
        self._wake_event.clear()
        triggers, self._requested_triggers = self._requested_triggers, set()
        return triggers

    async def _resolve_capture_cutoff(self, triggers: set[str]) -> PerceptionCutoff:
        if not self._include_audio or "session_stop" in triggers:
            return self._perception_runtime.capture_cutoff()

        cutoff = self._perception_runtime.capture_cutoff_if_speech_idle()
        if cutoff is None:
            cutoff = await self._perception_runtime.wait_for_speech_idle_cutoff(
                timeout=DEFAULT_MAX_SPEECH_DEFER_SEC
            )
            triggers.add("speech_boundary" if cutoff else "speech_defer_timeout")
        return cutoff or self._perception_runtime.capture_cutoff()

    async def _capture_batch(
        self, triggers: set[str], *, target_cutoff: PerceptionCutoff
    ) -> tuple[EnvMemoryBatch, PerceptionCutoff] | None:
        start = self._last_cutoff
        if target_cutoff.sequence <= start.sequence:
            return None
        read = self._perception_runtime.events.read_range(
            after_seq=start.sequence, until_seq=target_cutoff.sequence
        )
        if read.has_gap:
            raise EnvironmentBatchError("perception_gap")
        if not read.items:
            raise EnvironmentBatchError("perception_gap")
        end = self._context_state.message_sequence
        messages = self._context_state.messages_between(
            max(0, end - self._config.max_context_messages), end
        )

        def build() -> tuple[EnvMemoryBatch, PerceptionCutoff]:
            context = self._render_messages(messages)
            return self._builder.build(
                context_id=self.context_id,
                events=read.items,
                start_cutoff=start,
                target_cutoff=target_cutoff,
                triggers=triggers,
                chat_context=context[-self._config.max_context_chars :] if context else None,
                message_count=len(messages),
            )

        task = asyncio.create_task(
            asyncio.to_thread(build), name=f"memory_env_capture:{self.context_id}"
        )
        return await wait_for_cleanup(task)

    def _start_processor(self) -> None:
        if self._failure or not self._pending_batches:
            return
        if self._processor_task is None or self._processor_task.done():
            self._processor_task = asyncio.create_task(
                self._processor_loop(), name=f"memory_env_processor:{self.context_id}"
            )
            self._processor_task.add_done_callback(self._processor_done)

    async def _capture_and_enqueue(
        self,
        triggers: set[str],
        *,
        annotation_grace_sec: float | None = None,
        target_cutoff: PerceptionCutoff | None = None,
    ) -> bool:
        if not triggers or self._failure:
            return False
        async with self._capture_lock:
            if self._failure:
                return False
            if len(self._pending_batches) >= self._config.max_pending_batches:
                self._requested_triggers.update(triggers)
                return False
            try:
                target = target_cutoff or await self._resolve_capture_cutoff(triggers)
                grace = (
                    DEFAULT_ANNOTATION_GRACE_SEC
                    if annotation_grace_sec is None
                    else annotation_grace_sec
                )
                if grace > 0:
                    await asyncio.sleep(grace)
                result = await self._capture_batch(triggers, target_cutoff=target)
                if result is None or self._failure:
                    return False
                batch, cutoff = result
                # Admission and cursor advancement have no await. Pending work is never merged
                # with a retrying active batch, so new capture cannot reset its retry budget.
                self._pending_batches.append(batch)
                self._last_cutoff = cutoff
                self._perception_runtime.events.commit(
                    consumer_id=self._consumer_id, cursor_seq=cutoff.sequence
                )
                if cutoff.sequence < target.sequence:
                    self._requested_triggers.update(triggers)
                self._start_processor()
                return True
            except EnvironmentBatchError as error:
                self._halt(str(error))
                return False
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.error(
                    "ENV capture failed context=%s error_type=%s",
                    self.context_id,
                    type(error).__name__,
                )
                self._halt("capture_failed")
                return False

    def _advance(self, batch: EnvMemoryBatch) -> None:
        if batch.from_sequence != self._committed_sequence:
            raise RuntimeError("ENV committed batch is not contiguous")
        self._committed_sequence = batch.to_sequence
        self._active_batch = None

    async def _processor_loop(self) -> None:
        try:
            while self._pending_batches and not self._failure:
                batch = self._active_batch = self._pending_batches.popleft()
                if self._requested_triggers:
                    self._wake_event.set()
                while batch.attempts < self._config.max_attempts:
                    batch.attempts += 1
                    try:
                        await self._process(batch, self._config.process_timeout_sec)
                    except asyncio.CancelledError:
                        if batch.committed:
                            self._advance(batch)
                        raise
                    except Exception as error:
                        logger.warning(
                            "ENV batch failed context=%s attempt=%d error_type=%s",
                            self.context_id,
                            batch.attempts,
                            type(error).__name__,
                        )
                        if batch.committed:
                            self._advance(batch)
                            self._halt("post_commit_failed")
                            return
                        if batch.attempts >= self._config.max_attempts:
                            self._halt("retry_exhausted")
                            return
                        await asyncio.sleep(DEFAULT_RETRY_DELAY_SEC)
                    else:
                        batch.committed = True
                        self._advance(batch)
                        break
        except asyncio.CancelledError:
            if not self._stopping:
                self._halt("processor_cancelled")
            raise

    def _processor_done(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            if not self._stopping:
                self._halt("processor_cancelled")
        elif task.exception() is not None:
            self._halt("processor_failed")

    async def _scheduler_loop(self) -> None:
        while not self._stopping and not self._failure:
            try:
                await asyncio.wait_for(self._wake_event.wait(), DEFAULT_ENV_MEMORY_INTERVAL_SEC)
                triggers = self._take_requested_triggers()
            except TimeoutError:
                triggers = {"periodic"}
            if not self._failure:
                await self._capture_and_enqueue(triggers)

    def request(self, trigger: str) -> None:
        if not self._stopping and not self._failure and (trigger := trigger.strip()):
            self._requested_triggers.add(trigger)
            self._wake_event.set()

    async def start(self) -> None:
        if self._stop_task is not None:
            raise RuntimeError("ENV scheduler cannot restart after stopping")
        if self._scheduler_task is None:
            self._scheduler_task = asyncio.create_task(
                self._scheduler_loop(), name=f"memory_env_scheduler:{self.context_id}"
            )

    async def _shutdown(self, *, finalize: bool) -> None:
        final_cutoff = self._perception_runtime.capture_cutoff()
        try:
            async with asyncio.timeout(self._config.shutdown_timeout_sec):
                if self._scheduler_task is not None:
                    self._scheduler_task.cancel()
                    await asyncio.gather(self._scheduler_task, return_exceptions=True)

                if not finalize:
                    return
                while not self._failure:
                    self._start_processor()
                    if self._processor_task is not None:
                        await asyncio.shield(self._processor_task)
                    if self._last_cutoff.sequence >= final_cutoff.sequence:
                        break
                    if not await self._capture_and_enqueue(
                        {"session_stop"}, annotation_grace_sec=0, target_cutoff=final_cutoff
                    ):
                        break
        except TimeoutError:
            self._halt("shutdown_timeout")
        except asyncio.CancelledError:
            if self._processor_task is not None and self._processor_task.cancelled():
                self._halt("processor_cancelled")
            else:
                raise
        finally:
            tasks = tuple(task for task in (self._scheduler_task, self._processor_task) if task)
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._scheduler_task = self._processor_task = None
            self._requested_triggers.clear()
            self._wake_event.clear()
            self._perception_runtime.events.clear_consumer(self._consumer_id)
            logger.info("ENV scheduler stopped status=%s", self.status)

    async def stop(self, *, finalize: bool = True) -> None:
        if self._stop_task is None:
            self._stopping = True
            self._stop_task = asyncio.create_task(
                self._shutdown(finalize=finalize), name=f"memory_env_shutdown:{self.context_id}"
            )
        await wait_for_cleanup(self._stop_task)
