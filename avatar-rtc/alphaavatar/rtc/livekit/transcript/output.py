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
from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite
from typing import Any

from livekit import rtc

from alphaavatar.core.cleanup import wait_for_cleanup
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
    immediate: bool
    text: str = ""
    writer: Any = None
    closing: asyncio.Task | None = None


class LiveKitTranscriptOutput:
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
        self._finalized: OrderedDict[str, int] = OrderedDict()
        self._floor = 0
        self._subscription = self._task = self._close_task = self._start_task = None

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

    def _remember(self, output_id: str, sequence: int) -> None:
        self._finalized[output_id] = sequence
        while len(self._finalized) > 1024:
            _, old_sequence = self._finalized.popitem(last=False)
            self._floor = max(self._floor, old_sequence)

    async def _finish(self, output_id: str, sequence: int, *, interrupted: bool) -> None:
        state = self._states.get(output_id)
        self._remember(output_id, sequence)
        if state is None:
            return

        if state.closing is None:

            async def close() -> None:
                errors = []
                if self._legacy and state.text:
                    try:
                        async with asyncio.timeout(self._timeout):
                            await self._publish_legacy(state, final=True)
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
                    except Exception as exc:
                        errors.append(exc)
                self._states.pop(output_id, None)
                if errors:
                    raise ExceptionGroup("Transcript finalization failed", errors)

            state.closing = asyncio.create_task(close(), name="transcript_writer_close")
        await wait_for_cleanup(state.closing)

    async def _handle(self, event: OutputEvent) -> None:
        output = event.output
        payload, output_id = output.payload, output.output_id
        if isinstance(payload, OutputControl):
            if payload.type == OutputControlType.INTERRUPT:
                for identity in payload.targets:
                    if self._output.text_mode(identity.output_id) == OutputTextMode.IMMEDIATE:
                        await self._finish(identity.output_id, event.sequence, interrupted=True)
                return
            if (
                output_id
                and self._output.text_mode(output_id) == OutputTextMode.IMMEDIATE
                and payload.type in (OutputControlType.TEXT_COMPLETE, OutputControlType.COMPLETE)
            ):
                await self._finish(output_id, event.sequence, interrupted=False)
            return
        if not output_id or output_id in self._finalized or event.sequence <= self._floor:
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
            await self._finish(output_id, event.sequence, interrupted=interrupted)

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
                if event.output.output_id:
                    try:
                        async with asyncio.timeout(self._timeout):
                            await self._finish(
                                event.output.output_id, event.sequence, interrupted=True
                            )
                    except Exception:
                        logger.exception(
                            "Transcript cleanup failed output_id=%s", event.output.output_id
                        )

    async def _start(self) -> None:
        self._subscription = await self._output.stream.subscribe(
            self._name,
            kinds=(OutputKind.TEXT_CHUNK, OutputKind.TRANSCRIPT_CHUNK, OutputKind.CONTROL),
            lanes=self._lanes,
            max_pending=256,
            reliable=True,
        )
        self._task = asyncio.create_task(self._run(), name=self._name)

    async def on_session_start(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("Output consumer is closing or closed")
        if self._start_task is None:
            self._start_task = asyncio.create_task(self._start(), name="output_consumer_start")
        try:
            await asyncio.shield(self._start_task)
            if self._close_task is not None:
                raise RuntimeError("Output consumer closed during startup")
        except BaseException as original:
            try:
                await self.on_session_stop()
            except BaseException as cleanup:
                raise original from cleanup
            raise

    async def _close(self) -> None:
        if self._start_task is not None:
            if not self._start_task.done():
                self._start_task.cancel()
            await asyncio.gather(self._start_task, return_exceptions=True)
        if self._task is not None:
            self._task.cancel()
        if self._subscription is not None:
            await self._output.stream.unsubscribe(self._name)
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)
        errors = []
        for output_id in tuple(self._states):
            try:
                async with asyncio.timeout(self._timeout):
                    await self._finish(output_id, self._floor, interrupted=True)
            except Exception as exc:
                errors.append(exc)
        self._subscription = self._task = None
        if errors:
            raise ExceptionGroup("Transcript transport cleanup failed", errors)

    async def on_session_stop(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="transcript_transport_close")
        await wait_for_cleanup(self._close_task)
