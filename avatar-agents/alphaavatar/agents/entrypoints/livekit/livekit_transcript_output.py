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
"""LiveKit transport adapter for synchronized AlphaAvatar transcripts."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from alphaavatar.agents.log import logger
from alphaavatar.agents.runtime.plugin import AvatarRuntimePlugin
from alphaavatar.core.output import (
    OutputEvent,
    OutputKind,
    OutputLane,
    OutputRuntime,
    OutputSubscription,
    OutputTranscriptChunk,
)
from livekit import rtc


@dataclass(slots=True)
class _TranscriptState:
    output_id: str
    turn_id: str | None
    lane: OutputLane
    segment_id: str
    text: str = ""
    writer: Any | None = None


class LiveKitTranscriptOutput(AvatarRuntimePlugin):
    """
    Publish synchronized transcript increments through LiveKit.

    TRANSCRIPT_CHUNK contains only text confirmed by actual audio playout.
    The adapter keeps one LiveKit transcription segment per output_id and
    updates it incrementally until the output finishes or is interrupted.
    """

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
        lanes: tuple[OutputLane, ...] = (OutputLane.TRANSIENT,),
        subscription_name: str = "livekit:transcript_output",
        publish_legacy: bool = True,
        publish_text_stream: bool = True,
    ) -> None:
        if not publish_legacy and not publish_text_stream:
            raise ValueError("At least one LiveKit transcript protocol must be enabled")

        self._room = room
        self._output = output_runtime
        self._track_sid = track_sid
        self._lanes = lanes
        self._subscription_name = subscription_name
        self._publish_legacy_enabled = publish_legacy
        self._publish_text_stream_enabled = publish_text_stream

        self._subscription: OutputSubscription | None = None
        self._run_task: asyncio.Task[None] | None = None
        self._states: dict[str, _TranscriptState] = {}
        self._finalized_outputs: set[str] = set()

    async def on_session_start(self) -> None:
        if self._run_task is not None:
            return

        self._subscription = await self._output.stream.subscribe(
            self._subscription_name,
            kinds=(OutputKind.TRANSCRIPT_CHUNK,),
            lanes=self._lanes,
            max_pending=256,
            reliable=True,
        )
        self._run_task = asyncio.create_task(self._run(), name=self._subscription_name)

        logger.info(
            "LiveKit transcript output started lanes=%s legacy=%s text_stream=%s",
            [lane.value for lane in self._lanes],
            self._publish_legacy_enabled,
            self._publish_text_stream_enabled,
        )

    async def on_session_stop(self) -> None:
        run_task = self._run_task
        self._run_task = None

        if run_task is not None and not run_task.done():
            run_task.cancel()
        if run_task is not None:
            await asyncio.gather(run_task, return_exceptions=True)

        if self._subscription is not None:
            await self._output.stream.unsubscribe(self._subscription_name)

        states = tuple(self._states.values())
        self._states.clear()
        self._finalized_outputs.clear()

        if states:
            await asyncio.gather(
                *(self._close_writer(state, interrupted=True) for state in states),
                return_exceptions=True,
            )

        self._subscription = None
        logger.info("LiveKit transcript output stopped")

    async def _run(self) -> None:
        subscription = self._subscription
        if subscription is None:
            return

        try:
            while True:
                event = await subscription.get()

                try:
                    await self._handle_event(event)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Failed to publish transcript event_id=%s output_id=%s sequence=%s",
                        event.event_id,
                        event.output_id,
                        event.sequence,
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("LiveKit transcript output stopped unexpectedly")

    async def _handle_event(self, event: OutputEvent) -> None:
        payload = event.payload
        output_id = event.output_id

        if not isinstance(payload, OutputTranscriptChunk) or not output_id:
            return

        if output_id in self._finalized_outputs:
            return

        state = self._states.get(output_id)

        # An output interrupted before any audio text was delivered should not
        # create an empty message in the frontend.
        if state is None and payload.is_final and not payload.text:
            self._finalized_outputs.add(output_id)
            return

        if state is None:
            state = _TranscriptState(
                output_id=output_id,
                turn_id=event.turn_id,
                lane=event.lane,
                segment_id=self._segment_id(event.lane, output_id),
            )
            self._states[output_id] = state
        elif state.turn_id != event.turn_id or state.lane != event.lane:
            raise ValueError(f"Transcript identity mismatch output_id={output_id!r}")

        if payload.text:
            state.text += payload.text

            await asyncio.gather(
                self._write_text_stream(state, payload.text, event)
                if self._publish_text_stream_enabled
                else self._noop(),
                self._publish_legacy(state, event, final=False)
                if self._publish_legacy_enabled
                else self._noop(),
            )

        if not payload.is_final:
            return

        # Publish the final cumulative legacy segment even when the final
        # TRANSCRIPT_CHUNK contains no additional text.
        if self._publish_legacy_enabled:
            await self._publish_legacy(state, event, final=True)

        if self._publish_text_stream_enabled:
            await self._close_writer(state, interrupted=payload.interrupted)

        self._states.pop(output_id, None)
        self._finalized_outputs.add(output_id)

        logger.debug(
            "Finalized LiveKit transcript output_id=%s segment_id=%s interrupted=%s text=%r",
            output_id,
            state.segment_id,
            payload.interrupted,
            state.text,
        )

    async def _write_text_stream(
        self,
        state: _TranscriptState,
        text: str,
        event: OutputEvent,
    ) -> None:
        try:
            writer = await self._ensure_writer(state, event)
            await writer.write(text)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to write LiveKit transcript stream output_id=%s segment_id=%s",
                state.output_id,
                state.segment_id,
            )

    async def _ensure_writer(self, state: _TranscriptState, event: OutputEvent):
        if state.writer is not None:
            return state.writer

        participant = self._local_participant()
        stream_text = getattr(participant, "stream_text", None)
        if not callable(stream_text):
            raise RuntimeError("LiveKit local participant has no stream_text method")

        attributes = self._stream_attributes(state, event, final=False, interrupted=False)
        state.writer = await stream_text(
            topic=self.TRANSCRIPTION_TOPIC,
            sender_identity=participant.identity,
            attributes=attributes,
        )
        return state.writer

    async def _close_writer(self, state: _TranscriptState, *, interrupted: bool) -> None:
        writer = state.writer
        state.writer = None

        if writer is None:
            return

        close = getattr(writer, "aclose", None)
        if not callable(close):
            return

        attributes = {
            self.ATTR_FINAL: "true",
            self.ATTR_SEGMENT_ID: state.segment_id,
            "alphaavatar.output_id": state.output_id,
            "alphaavatar.turn_id": state.turn_id or "",
            "alphaavatar.lane": state.lane.value,
            "alphaavatar.interrupted": str(interrupted).lower(),
        }

        track_sid = self._resolve_track_sid()
        if track_sid:
            attributes[self.ATTR_TRACK_ID] = track_sid

        try:
            result = close(attributes=attributes)
            if inspect.isawaitable(result):
                await result
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to close LiveKit transcript stream output_id=%s segment_id=%s",
                state.output_id,
                state.segment_id,
            )

    async def _publish_legacy(
        self,
        state: _TranscriptState,
        event: OutputEvent,
        *,
        final: bool,
    ) -> None:
        try:
            participant = self._local_participant()
            transcription = rtc.Transcription(
                participant_identity=participant.identity,
                track_sid=self._resolve_track_sid() or "",
                segments=[
                    rtc.TranscriptionSegment(
                        id=state.segment_id,
                        text=state.text,
                        start_time=0,
                        end_time=0,
                        final=final,
                        language=self._language(event),
                    )
                ],
            )
            await participant.publish_transcription(transcription)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to publish legacy LiveKit transcript output_id=%s segment_id=%s final=%s",
                state.output_id,
                state.segment_id,
                final,
            )

    def _stream_attributes(
        self,
        state: _TranscriptState,
        event: OutputEvent,
        *,
        final: bool,
        interrupted: bool,
    ) -> dict[str, str]:
        attributes = {
            self.ATTR_FINAL: str(final).lower(),
            self.ATTR_SEGMENT_ID: state.segment_id,
            "alphaavatar.type": "output_transcript",
            "alphaavatar.output_id": state.output_id,
            "alphaavatar.turn_id": state.turn_id or "",
            "alphaavatar.lane": state.lane.value,
            "alphaavatar.event_id": event.event_id,
            "alphaavatar.sequence": str(event.sequence),
            "alphaavatar.interrupted": str(interrupted).lower(),
        }

        track_sid = self._resolve_track_sid()
        if track_sid:
            attributes[self.ATTR_TRACK_ID] = track_sid

        return attributes

    def _resolve_track_sid(self) -> str | None:
        if self._track_sid is None:
            return None

        try:
            return self._track_sid()
        except Exception:
            logger.exception("Failed to resolve transcript audio track SID")
            return None

    def _local_participant(self):
        participant = getattr(self._room, "local_participant", None)
        if participant is None:
            raise RuntimeError("LiveKit room has no local participant")
        return participant

    @staticmethod
    def _segment_id(lane: OutputLane, output_id: str) -> str:
        return f"SG_{lane.value}_{output_id}"

    @staticmethod
    def _language(event: OutputEvent) -> str:
        language = event.metadata.get("language")
        return language if isinstance(language, str) else ""

    @staticmethod
    async def _noop() -> None:
        return None
