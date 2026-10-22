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
from collections import deque
from dataclasses import dataclass, field

from alphaavatar.agents.avatar.voice import TTSStreamBase
from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.env.schemas.metadata import OutputMetadata
from alphaavatar.core.media import AudioFrame
from alphaavatar.core.output.enums.message_phase import OutputMessagePhase
from alphaavatar.core.output.schemas import OutputIdentity, OutputSource, OutputTextChunk

from ..speech_text import chunk_end


@dataclass(frozen=True, slots=True)
class SpeechLimits:
    max_outputs: int
    max_chars: int
    segment_chars: int
    min_chars: int
    flush_interval: float
    timeout: float
    audio_seconds: float
    audio_bytes: int


@dataclass(slots=True)
class TextPiece:
    chunk_id: str
    text: str


@dataclass(slots=True)
class PreparedSpeech:
    text: str
    source_chunk_ids: tuple[str, ...]
    stream: TTSStreamBase | None
    first: AudioFrame | None
    index: int
    final: bool
    first_audio_ms: float
    close_task: asyncio.Task[None] | None = None

    async def aclose(self) -> None:
        if self.stream is not None:
            if self.close_task is None:
                self.close_task = asyncio.create_task(
                    self.stream.aclose(), name="speech_stream_close"
                )
            await wait_for_cleanup(self.close_task)


@dataclass(slots=True)
class SpeechJob:
    identity: OutputIdentity
    source: OutputSource
    metadata: OutputMetadata
    pieces: deque[TextPiece] = field(default_factory=deque)
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    pending_chars: int = 0
    ended: bool = False
    cancelled: bool = False
    cancel_reason: str | None = None
    phase: OutputMessagePhase | None = None
    audio_attempted: bool = False
    segments: int = 0
    published_audio_seconds: float = 0.0
    first_audio_seconds: float = 0.8
    budget_rate: float = 14.0
    playback_sequence: int = 0
    playback_ns: int = 0
    playback_checked_ns: int = 0
    played_seconds: float = 0.0
    playback_valid: bool = False
    task: asyncio.Task | None = None
    running: bool = False
    handoff: asyncio.Task[None] | None = None
    prefetched: PreparedSpeech | None = None
    owns_handoff_slot: bool = False
    preparation_error: Exception | None = None

    def append(self, chunk: OutputTextChunk) -> None:
        if chunk.text:
            self.pieces.append(TextPiece(chunk.chunk_id, chunk.text))
            self.pending_chars += len(chunk.text)
        self.ended = self.ended or chunk.is_final
        self.changed.set()

    def peek(self, limit: int) -> str:
        parts, length = [], 0
        for piece in self.pieces:
            part = piece.text[: limit - length]
            parts.append(part)
            length += len(part)
            if length >= limit:
                break
        return "".join(parts)

    def take(
        self,
        *,
        max_chars: int,
        min_chars: int,
        flush: bool,
        target_chars: int | None = None,
        eager: bool = True,
    ) -> tuple[str, tuple[str, ...]]:
        # Lookahead confirms a decimal/abbreviation without joining the entire answer.
        text = self.peek(2 * max_chars + 64)
        end = chunk_end(
            text,
            minimum=min_chars,
            maximum=max_chars,
            target=target_chars,
            flush=flush or self.ended,
            final=self.ended and len(text) == self.pending_chars,
            eager=eager,
        )
        if not end:
            return "", ()

        remaining, chunks = end, []
        while remaining:
            piece = self.pieces[0]
            used = min(remaining, len(piece.text))
            chunks.append(piece.chunk_id)
            piece.text = piece.text[used:]
            remaining -= used
            if not piece.text:
                self.pieces.popleft()

        self.pending_chars -= end
        return text[:end], tuple(dict.fromkeys(chunks))
