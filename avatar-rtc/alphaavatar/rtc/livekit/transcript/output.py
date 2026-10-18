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
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from math import isfinite
from typing import Any

from livekit import rtc

from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.lifecycle import LifecycleComponent
from alphaavatar.core.log.events import log_event
from alphaavatar.core.output import OutputRuntime
from alphaavatar.core.output.enums import OutputControlType, OutputKind, OutputLane, OutputTextMode
from alphaavatar.core.output.schemas import (
    OutputControl,
    OutputEvent,
    OutputIdentity,
    OutputTextChunk,
    OutputTranscriptChunk,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _Transcript:
    identity: OutputIdentity
    segment_id: str
    source_text: bool
    pending: deque[str] = field(default_factory=deque)
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    text: str = ""
    retained_chars: int = 0
    ended: bool = False
    interrupted: bool = False
    running: bool = False
    finalizing: bool = False
    terminal_interrupted: bool = False
    reported: bool = False
    writer: Any = None
    task: asyncio.Task | None = None


class LiveKitTranscriptOutput(LifecycleComponent):
    """Send only synchronizer-released captions in audio mode, with independent network I/O."""

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
        max_output_chars: int = 65_536,
        max_total_chars: int = 262_144,
    ) -> None:
        if not publish_legacy and not publish_text_stream:
            raise ValueError("At least one transcript protocol must be enabled")
        if any(
            type(value) is not int or value < 1
            for value in (max_pending_outputs, max_output_chars, max_total_chars)
        ):
            raise ValueError("Transcript capacities must be positive integers")
        if (
            max_output_chars > max_total_chars
            or not isfinite(publish_timeout)
            or publish_timeout <= 0
        ):
            raise ValueError("Transcript limits must be positive and consistent")

        self._room, self._output, self._track_sid = room, output_runtime, track_sid
        self._lanes, self._name = lanes, subscription_name
        self._legacy, self._text_stream = publish_legacy, publish_text_stream
        self._timeout, self._capacity = publish_timeout, max_pending_outputs
        self._max_output_chars, self._max_total_chars = max_output_chars, max_total_chars
        self._retained_chars = 0
        self._states: dict[str, _Transcript] = {}
        self._finalized: OrderedDict[str, None] = OrderedDict()
        self._senders: set[asyncio.Task] = set()
        self._failures: list[Exception] = []
        self._failed = asyncio.Event()
        self._subscription = None
        self._task: asyncio.Task | None = None
        self._start_task: asyncio.Task | None = None
        self._close_task: asyncio.Task | None = None
        self._retirement: asyncio.Task | None = None
        self._intake_stopping = self._intake_observed = False

    def _remember(self, output_id: str) -> None:
        self._finalized[output_id] = None
        self._finalized.move_to_end(output_id)
        while len(self._finalized) > 1024:
            self._finalized.popitem(last=False)

    def _fail(self, error: Exception) -> None:
        if all(value is not error for value in self._failures):
            self._failures.append(error)
            logger.error("Transcript transport failed", exc_info=error)
        self._failed.set()
        if self._subscription is not None and self._retirement is None:
            self._retirement = asyncio.create_task(
                self._subscription.fail(error), name="transcript_consumer_retirement"
            )
            self._retirement.add_done_callback(self._observe_retirement)

    @staticmethod
    def _observe_retirement(task: asyncio.Task) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("Transcript retirement failed", exc_info=error)

    async def wait_failed(self) -> None:
        await self._failed.wait()
        raise RuntimeError("Transcript transport is unavailable") from self._failures[0]

    def _attributes(self, state: _Transcript, *, final: bool) -> dict[str, str]:
        identity = state.identity
        attributes = {
            self.ATTR_FINAL: str(final).lower(),
            self.ATTR_SEGMENT_ID: state.segment_id,
            "alphaavatar.type": "output_text" if state.source_text else "output_transcript",
            "alphaavatar.delivery": "generated" if state.source_text else "local_audio_queue",
            "alphaavatar.output_id": identity.output_id,
            "alphaavatar.turn_id": identity.scope.turn_id or "",
            "alphaavatar.run_id": identity.scope.run_id or "",
            "alphaavatar.lane": identity.lane.value,
            "alphaavatar.interrupted": str(state.interrupted or state.terminal_interrupted).lower(),
        }
        # Generated text is not a transcript of a played track and must not be gated by that track.
        if not state.source_text and self._track_sid is not None:
            if track_id := self._track_sid():
                attributes[self.ATTR_TRACK_ID] = track_id
        return attributes

    async def _legacy_snapshot(self, state: _Transcript, *, final: bool) -> None:
        participant = self._room.local_participant
        track_id = (
            self._track_sid() if not state.source_text and self._track_sid is not None else ""
        )
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

    def _diagnose(self, state: _Transcript, name: str) -> None:
        identity = state.identity
        log_event(
            logger,
            name,
            session_id=self._output.session_id,
            context_id=identity.scope.context_id,
            turn_id=identity.scope.turn_id,
            run_id=identity.scope.run_id,
            output_id=identity.output_id,
            delivery="generated" if state.source_text else "local_audio_queue",
            text_chars=len(state.text),
            interrupted=state.interrupted or state.terminal_interrupted,
            stage="local_transport",
        )

    async def _write(self, state: _Transcript, text: str) -> None:
        participant = self._room.local_participant
        if self._text_stream and state.writer is None:

            async def open_writer() -> None:
                async with asyncio.timeout(self._timeout):
                    state.writer = await participant.stream_text(
                        topic=self.TRANSCRIPTION_TOPIC,
                        sender_identity=participant.identity,
                        attributes=self._attributes(state, final=False),
                    )

            # A writer acquired after cancellation still belongs to this output's finalizer.
            await wait_for_cleanup(asyncio.create_task(open_writer(), name="transcript_open"))
        if state.interrupted or (
            state.source_text and not self._output.can_deliver(state.identity.output_id)
        ):
            state.interrupted = True
            return
        async with asyncio.timeout(self._timeout):
            if self._text_stream:
                await state.writer.write(text)
            state.text += text
            if self._legacy:
                await self._legacy_snapshot(state, final=False)
        if not state.reported:
            state.reported = True
            self._diagnose(state, "text.started")

    async def _finalize(self, state: _Transcript) -> None:
        errors: list[Exception] = []
        operations = []
        if self._legacy and state.text:
            operations.append(lambda: self._legacy_snapshot(state, final=True))
        if state.writer is not None:
            operations.append(
                lambda: state.writer.aclose(attributes=self._attributes(state, final=True))
            )
        for operation in operations:
            try:
                async with asyncio.timeout(self._timeout):
                    await operation()
            except asyncio.CancelledError as error:
                failure = RuntimeError("Transcript finalization cancelled itself")
                failure.__cause__ = error
                errors.append(failure)
            except Exception as error:
                errors.append(error)
        if errors:
            raise ExceptionGroup("Transcript finalization failed", errors)
        if state.text:
            self._diagnose(state, "text.finished")

    async def _deliver(self, state: _Transcript) -> None:
        state.running = True
        try:
            while not state.interrupted:
                state.changed.clear()
                if state.source_text and not self._output.can_deliver(state.identity.output_id):
                    state.interrupted = True
                    break
                if state.pending:
                    # Coalesce pending deltas without losing their order or their whitespace.
                    text = "".join(state.pending)
                    state.pending.clear()
                    await self._write(state, text)
                    continue
                if state.ended:
                    break
                await state.changed.wait()
        except asyncio.CancelledError as error:
            if not state.interrupted and self._close_task is None:
                failure = RuntimeError("Transcript writer cancelled without owner shutdown")
                failure.__cause__ = error
                self._fail(failure)
            state.interrupted = True
        except Exception as error:
            state.interrupted = True
            self._fail(error)
        finally:
            state.finalizing = True
            state.pending.clear()
            try:
                await wait_for_cleanup(
                    asyncio.create_task(self._finalize(state), name="transcript_writer_close")
                )
            except asyncio.CancelledError as error:
                failure = RuntimeError("Transcript writer settlement cancelled")
                failure.__cause__ = error
                self._fail(failure)
            except Exception as error:
                self._fail(error)
            finally:
                self._release(state)

    def _release(self, state: _Transcript) -> None:
        output_id = state.identity.output_id
        if self._states.get(output_id) is state:
            self._states.pop(output_id)
            self._retained_chars -= state.retained_chars
        state.pending.clear()
        self._remember(output_id)

    def _cancel(self, state: _Transcript) -> None:
        state.interrupted = state.ended = True
        state.pending.clear()
        state.changed.set()
        task = state.task
        if (
            task is not None
            and state.running
            and not state.finalizing
            and not task.done()
            and not task.cancelling()
        ):
            task.cancel()

    def _observe_sender(self, state: _Transcript, task: asyncio.Task) -> None:
        self._senders.discard(task)
        if task.cancelled():
            self._release(state)
            self._fail(RuntimeError("Transcript writer exited without settlement"))
        elif (error := task.exception()) is not None:
            self._release(state)
            self._fail(error)

    def _source_mode(self, output_id: str) -> bool:
        mode = self._output.text_mode(output_id)
        return mode == OutputTextMode.IMMEDIATE

    def _ingest(self, event: OutputEvent) -> None:
        output = event.output
        payload, output_id = output.payload, output.output_id
        if isinstance(payload, OutputControl):
            if payload.type == OutputControlType.INTERRUPT:
                for identity in payload.targets:
                    if not self._source_mode(identity.output_id):
                        continue
                    state = self._states.get(identity.output_id)
                    if state is not None:
                        if state.identity != identity:
                            raise ValueError("Transcript interruption identity changed")
                        self._cancel(state)
                    else:
                        self._remember(identity.output_id)
            elif (
                output_id
                and self._source_mode(output_id)
                and payload.type in (OutputControlType.TEXT_COMPLETE, OutputControlType.COMPLETE)
            ):
                if (state := self._states.get(output_id)) is not None:
                    if state.identity != OutputIdentity(output_id, output.lane, output.scope):
                        raise ValueError("Transcript completion identity changed")
                    state.ended = True
                    state.changed.set()
                else:
                    self._remember(output_id)
            return

        if not output_id or output_id in self._finalized:
            return

        source_text = isinstance(payload, OutputTextChunk)
        if source_text:
            if (
                not self._source_mode(output_id)
                or payload.mode != self._output.text_mode(output_id)
                or not self._output.can_deliver(output_id)
            ):
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
                raise RuntimeError("Transcript output capacity exhausted")
            if (
                len(text) > self._max_output_chars
                or self._retained_chars + len(text) > self._max_total_chars
            ):
                raise RuntimeError("Transcript text capacity exhausted")
            state = _Transcript(identity, f"SG_{identity.lane.value}_{output_id}", source_text)
            self._states[output_id] = state
            state.task = asyncio.create_task(self._deliver(state), name=f"transcript:{output_id}")
            self._senders.add(state.task)
            state.task.add_done_callback(lambda task: self._observe_sender(state, task))

        if state is not None:
            if (state.identity, state.source_text) != (identity, source_text):
                raise ValueError("Transcript delivery identity changed")
            if state.interrupted:
                return
            if state.ended:
                if text:
                    raise ValueError("Transcript text followed completion")
                return
            if (
                state.retained_chars + len(text) > self._max_output_chars
                or self._retained_chars + len(text) > self._max_total_chars
            ):
                raise RuntimeError("Transcript text capacity exhausted")

            if text:
                state.pending.append(text)
                state.retained_chars += len(text)
                self._retained_chars += len(text)

            # A synchronized final can retain the already confirmed prefix on interruption.
            state.ended = final
            state.terminal_interrupted = interrupted
            if interrupted and source_text:
                self._cancel(state)
            state.changed.set()
        elif final:
            self._remember(output_id)

    async def _run(self) -> None:
        while True:
            self._ingest(await self._subscription.get())

    def _observe_intake(self, task: asyncio.Task) -> None:
        if self._intake_observed:
            return
        self._intake_observed = True
        if task.cancelled():
            if self._intake_stopping:
                return
            self._fail(RuntimeError("Transcript intake cancelled without owner shutdown"))
        elif (error := task.exception()) is not None:
            self._fail(error)
        elif not self._intake_stopping:
            self._fail(RuntimeError("Transcript intake stopped unexpectedly"))

    async def _start(self) -> None:
        kinds = (OutputKind.TEXT_CHUNK, OutputKind.TRANSCRIPT_CHUNK, OutputKind.CONTROL)
        self._subscription = await self._output.stream.subscribe(
            self._name,
            kinds=kinds,
            lanes=self._lanes,
            max_pending=256,
            reliable=True,
            fail_on_overflow=True,
            control_types=(
                OutputControlType.INTERRUPT,
                OutputControlType.TEXT_COMPLETE,
                OutputControlType.COMPLETE,
            ),
        )
        self._task = asyncio.create_task(self._run(), name=self._name)
        self._task.add_done_callback(self._observe_intake)

    async def on_start(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("Transcript output is closing or closed")
        if self._start_task is None:
            self._start_task = asyncio.create_task(self._start(), name="transcript_start")
        try:
            await asyncio.shield(self._start_task)
            if self._close_task is not None or self._failed.is_set():
                raise RuntimeError("Transcript output failed during startup")
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

        if self._task is not None:
            if self._task.done():
                self._observe_intake(self._task)
            elif not self._task.cancelling():
                self._intake_stopping = True
                self._task.cancel()
        try:
            if self._subscription is not None:
                await self._output.stream.unsubscribe(self._name)
        except Exception as error:
            self._fail(error)
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)
            self._observe_intake(self._task)
        for state in tuple(self._states.values()):
            self._cancel(state)
        await asyncio.gather(*tuple(self._senders), return_exceptions=True)
        if self._retirement is not None:
            try:
                await wait_for_cleanup(self._retirement)
            except Exception as error:
                self._fail(error)
        self._subscription = None
        if self._failures:
            raise ExceptionGroup("Transcript output cleanup failed", self._failures)

    async def on_stop(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="transcript_close")
        await wait_for_cleanup(self._close_task)
