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
"""AlphaAvatar transcription events to LiveKit speech events."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable

from livekit import rtc
from livekit.agents import stt as livekit_stt

from alphaavatar.agents.log import logger

from .schema.transcription import (
    TranscriptionEvent,
    TranscriptionEventType,
)


class LiveKitTranscriptionAdapter:
    """
    Bridges AlphaAvatar-owned transcription into LiveKit turn handling.

    AlphaAvatar owns STT inference, while LiveKit temporarily continues to
    consume SpeechEvent objects for endpointing and turn commitment.
    """

    def __init__(self) -> None:
        self._events: asyncio.Queue[livekit_stt.SpeechEvent] = asyncio.Queue()

    def handle_event(self, event: TranscriptionEvent) -> None:
        if event.type == TranscriptionEventType.ERROR:
            logger.warning(
                "STT error source_id=%s segment_id=%s reason=%s",
                event.source_id,
                event.segment_id,
                event.reason,
            )
            return

        text = event.text.strip()
        if not text:
            return

        event_type = self._to_livekit_event_type(event.type)
        if event_type is None:
            return

        self._events.put_nowait(
            livekit_stt.SpeechEvent(
                type=event_type,
                request_id=event.segment_id,
                alternatives=[
                    livekit_stt.SpeechData(
                        language=event.language or "en",
                        text=text,
                        start_time=event.start_time or 0.0,
                        end_time=event.end_time or 0.0,
                        confidence=event.confidence or 0.0,
                        speaker_id=event.source_id,
                    )
                ],
            )
        )

    def stream(
        self,
        audio: AsyncIterable[rtc.AudioFrame],
    ) -> AsyncIterable[livekit_stt.SpeechEvent]:
        async def _generate() -> AsyncIterable[livekit_stt.SpeechEvent]:
            drain_task = asyncio.create_task(
                self._drain_audio(audio),
                name="livekit_stt_audio_drain",
            )

            try:
                while True:
                    yield await self._events.get()
            finally:
                drain_task.cancel()
                await asyncio.gather(
                    drain_task,
                    return_exceptions=True,
                )

        return _generate()

    @staticmethod
    async def _drain_audio(
        audio: AsyncIterable[rtc.AudioFrame],
    ) -> None:
        async for _ in audio:
            pass

    @staticmethod
    def _to_livekit_event_type(
        event_type: TranscriptionEventType,
    ) -> livekit_stt.SpeechEventType | None:
        if event_type == TranscriptionEventType.INTERIM_TRANSCRIPT:
            return livekit_stt.SpeechEventType.INTERIM_TRANSCRIPT

        if event_type == TranscriptionEventType.FINAL_TRANSCRIPT:
            return livekit_stt.SpeechEventType.FINAL_TRANSCRIPT

        return None
