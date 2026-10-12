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
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from math import isfinite
from typing import Any

from livekit import rtc

from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.lifecycle import LifecycleComponent
from alphaavatar.core.output import OutputRuntime
from alphaavatar.core.output.enums import OutputControlType, OutputKind, OutputLane, OutputTextMode
from alphaavatar.core.output.schemas import (
    OutputControl,
    OutputEvent,
    OutputIdentity,
    OutputTextChunk,
    OutputTranscriptChunk,
)
from alphaavatar.core.output.stream import OutputSubscription

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _Transcript:
    identity: OutputIdentity
    segment_id: str
    immediate: bool
    text: str = ""
    writer: Any = None
    closing: asyncio.Task | None = None


class LiveKitTranscriptOutput(LifecycleComponent):
    """Deliver immediate source text or audio-synchronized phrases, never MIRROR content."""

    TRANSCRIPTION_TOPIC = "lk.transcription"
    ATTR_FINAL = "lk.transcription_final"
    ATTR_SEGMENT_ID = "lk.segment_id"
    ATTR_TRACK_ID = "lk.transcribed_track_id"

    def __init__(
        self,
        *,
        room: rtc.Room,
        output_runtime: OutputRuntime,
        track_sid: Callable[[], str | None] | None = None,
        lanes: tuple[OutputLane, ...] = (OutputLane.TRANSIENT, OutputLane.ASSISTANT),
        subscription_name: str = "livekit:transcript_output",
        publish_legacy: bool = True,
        publish_text_stream: bool = True,
        publish_timeout: float = 5.0,
        max_pending_outputs: int = 32,
    ) -> None:
        if not publish_legacy and not publish_text_stream:
            raise ValueError("At least one transcript protocol must be enabled")
        if max_pending_outputs < 1 or not isfinite(publish_timeout) or publish_timeout <= 0:
            raise ValueError("Transcript limits must be positive")

        self._room, self._output, self._track_sid = room, output_runtime, track_sid
        self._lanes, self._name = lanes, subscription_name
        self._legacy, self._text_stream = publish_legacy, publish_text_stream
        self._timeout, self._capacity = publish_timeout, max_pending_outputs
        self._states: dict[str, _Transcript] = {}
        self._finalized: OrderedDict[str, None] = OrderedDict()
        self._finalization_failure: Exception | None = None
        self._consumer_failure: Exception | None = None
        self._consumer_observed = self._consumer_stopping = False
        self._failure_task: asyncio.Task[None] | None = None
        self._subscription = self._task = self._close_task = self._start_task = None

    @staticmethod
    async def _settle_step(
        operation: Awaitable[None], errors: list[Exception], *, label: str
    ) -> None:
        try:
            await operation
        except asyncio.CancelledError as exc:
            error = RuntimeError(f"{label} cancelled itself")
            error.__cause__ = exc
            errors.append(error)
        except Exception as exc:
            errors.append(exc)

    @staticmethod
    def _observe_retirement(task: asyncio.Task[None]) -> None:
        if task.cancelled():
            logger.error("Transcript consumer retirement cancelled itself")
        elif (error := task.exception()) is not None:
            logger.error("Transcript consumer retirement failed", exc_info=error)

    def _attributes(self, state: _Transcript, *, final: bool, interrupted: bool) -> dict[str, str]:
        identity = state.identity
        attributes = {
            self.ATTR_FINAL: str(final).lower(),
            self.ATTR_SEGMENT_ID: state.segment_id,
            "alphaavatar.type": "output_text" if state.immediate else "output_transcript",
            "alphaavatar.output_id": identity.output_id,
            "alphaavatar.turn_id": identity.scope.turn_id or "",
            "alphaavatar.lane": identity.lane.value,
            "alphaavatar.interrupted": str(interrupted).lower(),
        }
        if not state.immediate and self._track_sid is not None:
            if track_id := self._track_sid():
                attributes[self.ATTR_TRACK_ID] = track_id
        return attributes

    async def _write(self, state: _Transcript, text: str) -> None:
        participant = self._room.local_participant
        if state.immediate and not self._output.can_deliver(state.identity.output_id):
            return

        if self._text_stream:
            if state.writer is None:

                async def open_writer() -> None:
                    async with asyncio.timeout(self._timeout):
                        state.writer = await participant.stream_text(
                            topic=self.TRANSCRIPTION_TOPIC,
                            sender_identity=participant.identity,
                            attributes=self._attributes(state, final=False, interrupted=False),
                        )

                await wait_for_cleanup(asyncio.create_task(open_writer(), name="transcript_open"))
            if state.immediate and not self._output.can_deliver(state.identity.output_id):
                return
            await state.writer.write(text)
        state.text += text
        if self._legacy:
            await self._publish_legacy(state, final=False)

    async def _publish_legacy(self, state: _Transcript, *, final: bool) -> None:
        participant = self._room.local_participant
        track_id = self._track_sid() if not state.immediate and self._track_sid is not None else ""
        await participant.publish_transcription(
            rtc.Transcription(
                participant_identity=participant.identity,
                track_sid=track_id or "",
                segments=[
                    rtc.TranscriptionSegment(
                        id=state.segment_id,
                        text=state.text,
                        start_time=0,
                        end_time=0,
                        final=final,
                        language="",
                    )
                ],
            )
        )

    def _remember(self, output_id: str) -> None:
        # A priority interrupt is not a stream cursor for unrelated outputs.
        self._finalized[output_id] = None
        self._finalized.move_to_end(output_id)
        while len(self._finalized) > 1024:
            self._finalized.popitem(last=False)

    async def _finish(self, output_id: str, *, interrupted: bool) -> None:
        state = self._states.get(output_id)
        self._remember(output_id)
        if state is None:
            return

        if state.closing is None:

            async def close() -> None:
                errors: list[Exception] = []
                try:
                    if self._legacy and state.text:
                        try:
                            async with asyncio.timeout(self._timeout):
                                await self._publish_legacy(state, final=True)
                        except asyncio.CancelledError as exc:
                            # Callers do not cancel this owned task; transport aborts are failures.
                            error = RuntimeError("Legacy transcript finalization cancelled itself")
                            error.__cause__ = exc
                            errors.append(error)
                        except Exception as exc:
                            errors.append(exc)
                    if state.writer is not None:
                        try:
                            async with asyncio.timeout(self._timeout):
                                await state.writer.aclose(
                                    attributes=self._attributes(
                                        state, final=True, interrupted=interrupted
                                    )
                                )
                        except asyncio.CancelledError as exc:
                            error = RuntimeError("Transcript writer finalization cancelled itself")
                            error.__cause__ = exc
                            errors.append(error)
                        except Exception as exc:
                            errors.append(exc)
                finally:
                    self._states.pop(output_id, None)
                if errors:
                    failure = ExceptionGroup("Transcript finalization failed", errors)
                    if self._finalization_failure is None:
                        self._finalization_failure = failure
                    raise failure

            state.closing = asyncio.create_task(close(), name="transcript_writer_close")
        await wait_for_cleanup(state.closing)

    async def _finish_many(
        self, identities: tuple[OutputIdentity, ...], *, interrupted: bool
    ) -> None:
        if not identities:
            return

        async def finish(identity: OutputIdentity) -> None:
            state = self._states.get(identity.output_id)
            if state is not None and state.identity != identity:
                raise ValueError("Transcript finalization identity changed")
            await self._finish(identity.output_id, interrupted=interrupted)

        async def settle() -> None:
            # Register every live target before suspension; historical identities need no task.
            pending = []
            for identity in identities:
                if identity.output_id in self._states:
                    pending.append(finish(identity))
                else:
                    self._remember(identity.output_id)
            results = await asyncio.gather(*pending, return_exceptions=True)
            errors: list[Exception] = []
            for result in results:
                if isinstance(result, asyncio.CancelledError):
                    error = RuntimeError("Transcript target settlement cancelled itself")
                    error.__cause__ = result
                    errors.append(error)
                elif isinstance(result, Exception):
                    errors.append(result)
                elif isinstance(result, BaseException):
                    raise result
            if errors:
                failure = ExceptionGroup("Transcript target settlement failed", errors)
                if self._finalization_failure is None:
                    self._finalization_failure = failure
                raise failure

        await wait_for_cleanup(asyncio.create_task(settle(), name="transcript_target_settlement"))

    async def _handle(self, event: OutputEvent) -> None:
        output = event.output
        payload, output_id = output.payload, output.output_id
        if isinstance(payload, OutputControl):
            if payload.type == OutputControlType.INTERRUPT:
                identities = tuple(
                    identity
                    for identity in payload.targets
                    if self._output.text_mode(identity.output_id) == OutputTextMode.IMMEDIATE
                )
                await self._finish_many(identities, interrupted=True)
                return
            if (
                output_id
                and self._output.text_mode(output_id) == OutputTextMode.IMMEDIATE
                and payload.type in (OutputControlType.TEXT_COMPLETE, OutputControlType.COMPLETE)
            ):
                await self._finish(output_id, interrupted=False)
            return

        if not output_id or output_id in self._finalized:
            return

        immediate = isinstance(payload, OutputTextChunk)
        if immediate:
            if payload.mode != OutputTextMode.IMMEDIATE or not self._output.can_deliver(output_id):
                return
            text, final, interrupted = payload.text, payload.is_final, False
        elif isinstance(payload, OutputTranscriptChunk):
            text, final, interrupted = payload.text, payload.is_final, payload.interrupted
        else:
            return
        identity = OutputIdentity(output_id, output.lane, output.scope)
        state = self._states.get(output_id)
        if state is None and text:
            if len(self._states) >= self._capacity:
                raise RuntimeError("Transcript transport capacity exhausted")
            state = _Transcript(identity, f"SG_{identity.lane.value}_{output_id}", immediate)
            self._states[output_id] = state
        if state is not None:
            if (state.identity, state.immediate) != (identity, immediate):
                raise ValueError("Transcript delivery identity changed")
            if text:
                await self._write(state, text)
        if final:
            await self._finish(output_id, interrupted=interrupted)

    async def _run(self) -> None:
        while True:
            event = await self._subscription.get()
            try:
                async with asyncio.timeout(self._timeout):
                    await self._handle(event)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Transcript delivery failed output_id=%s", event.output.output_id)
                # Retirement fails the subscription before settling every live writer.
                # Continuing here would silently drop later chunks of a locally finalized output.
                raise

    async def _retire_consumer(self, subscription: OutputSubscription, failure: Exception) -> None:
        errors: list[Exception] = []
        # Keep the failed subscription registered until owner teardown. Publishers must
        # receive a failure, not silently deliver into a queue that no longer has a reader.
        await self._settle_step(
            subscription.fail(failure), errors, label="Transcript failure admission"
        )
        await self._settle_step(
            self._finish_many(
                tuple(state.identity for state in self._states.values()), interrupted=True
            ),
            errors,
            label="Transcript failure settlement",
        )
        if errors:
            raise ExceptionGroup("Transcript consumer retirement failed", errors)

    def _observe_consumer(self, task: asyncio.Task[None]) -> None:
        if self._consumer_observed or not task.done():
            return
        self._consumer_observed = True
        try:
            task.result()
        except asyncio.CancelledError as exc:
            if self._consumer_stopping:
                return
            failure = RuntimeError("Transcript consumer cancelled without owner shutdown")
            failure.__cause__ = exc
        except Exception as exc:
            failure = exc
        else:
            if self._consumer_stopping:
                return
            failure = RuntimeError("Transcript consumer stopped unexpectedly")
        self._consumer_failure = failure
        logger.error("Transcript consumer failed", exc_info=failure)
        # A done callback also observes cancellation before the worker's first execution.
        self._failure_task = asyncio.create_task(
            self._retire_consumer(self._subscription, failure),
            name="transcript_consumer_retirement",
        )
        self._failure_task.add_done_callback(self._observe_retirement)

    async def _start(self) -> None:
        self._subscription = await self._output.stream.subscribe(
            self._name,
            kinds=(OutputKind.TEXT_CHUNK, OutputKind.TRANSCRIPT_CHUNK, OutputKind.CONTROL),
            lanes=self._lanes,
            max_pending=256,
            reliable=True,
        )
        self._task = asyncio.create_task(self._run(), name=self._name)
        self._task.add_done_callback(self._observe_consumer)

    async def on_start(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("Output consumer is closing or closed")
        if self._start_task is None:
            self._start_task = asyncio.create_task(self._start(), name="output_consumer_start")
        try:
            await asyncio.shield(self._start_task)
            if self._close_task is not None:
                raise RuntimeError("Output consumer closed during startup")
            if self._task.done():
                self._observe_consumer(self._task)
                raise RuntimeError(
                    "Transcript consumer failed during startup"
                ) from self._consumer_failure
        except BaseException as original:
            try:
                await self.on_stop()
            except BaseException as cleanup:
                raise original from cleanup
            raise

    async def _close(self) -> None:
        if self._start_task is not None:
            if not self._start_task.done():
                self._start_task.cancel()
            await asyncio.gather(self._start_task, return_exceptions=True)

        # Observe an already-dead worker before labeling subsequent cancellation as shutdown.
        if self._task is not None:
            self._observe_consumer(self._task)
        if self._task is not None and not self._task.done() and not self._task.cancelling():
            self._consumer_stopping = True
            self._task.cancel()

        errors: list[Exception] = []
        retirement = self._failure_task
        if retirement is not None:
            await self._settle_step(
                wait_for_cleanup(retirement), errors, label="Transcript consumer retirement"
            )
        if self._subscription is not None:
            await self._settle_step(
                self._output.stream.unsubscribe(self._name), errors, label="Transcript unsubscribe"
            )
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)
            self._observe_consumer(self._task)
        if self._failure_task is not None and self._failure_task is not retirement:
            await self._settle_step(
                wait_for_cleanup(self._failure_task), errors, label="Transcript consumer retirement"
            )

        # A failed reader's retirement may already have finalized and removed its writers.
        previous_failure = self._finalization_failure
        try:
            await self._settle_step(
                self._finish_many(
                    tuple(state.identity for state in self._states.values()), interrupted=True
                ),
                errors,
                label="Transcript shutdown settlement",
            )
        finally:
            self._subscription = self._task = None
        for failure in (self._consumer_failure, previous_failure):
            if failure is not None and all(error is not failure for error in errors):
                errors.append(failure)
        if errors:
            raise ExceptionGroup("Transcript transport cleanup failed", errors)

    async def on_stop(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="transcript_transport_close")
        await wait_for_cleanup(self._close_task)
