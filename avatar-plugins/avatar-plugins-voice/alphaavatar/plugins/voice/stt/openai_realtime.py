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
import base64
import json
import os
from collections import deque
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiohttp
import numpy as np
import soxr

from alphaavatar.agents.avatar.voice import (
    STTBase,
    STTCapabilities,
    STTInputMode,
    STTStreamBase,
    TranscriptionEvent,
    TranscriptionEventType,
)
from alphaavatar.core.media import AudioFrame, AudioSampleFormat

from ..log import logger

_TARGET_SAMPLE_RATE = 24_000
_FLUSH = object()
_END_INPUT = object()
_END_EVENTS = object()


@dataclass(slots=True, frozen=True)
class _FrameCommand:
    frame: AudioFrame
    segment_id: str


@dataclass(slots=True, frozen=True)
class _CommitCommand:
    segment_id: str


class OpenAIRealtimeSTT(STTBase):
    """
    OpenAI Realtime transcription provider.

    One stream corresponds to one ordered audio source and maintains one
    long-lived WebSocket connection across multiple speech segments.
    """

    def __init__(
        self,
        *,
        model: str = "gpt-realtime-whisper",
        language: str | None = None,
        delay: Literal["minimal", "low", "medium", "high", "xhigh"] = "low",
        api_key: str | None = None,
        base_url: str = "wss://api.openai.com/v1/realtime",
        safety_identifier: str | None = None,
        queue_size: int = 256,
        connect_timeout_sec: float = 10.0,
        drain_timeout_sec: float = 5.0,
    ) -> None:
        if not model:
            raise ValueError("OpenAI STT model cannot be empty")
        if queue_size <= 0:
            raise ValueError("queue_size must be positive")
        if connect_timeout_sec <= 0:
            raise ValueError("connect_timeout_sec must be positive")
        if drain_timeout_sec <= 0:
            raise ValueError("drain_timeout_sec must be positive")

        self._model = model
        self._language = language
        self._delay = delay
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._safety_identifier = safety_identifier
        self._queue_size = queue_size
        self._connect_timeout_sec = connect_timeout_sec
        self._drain_timeout_sec = drain_timeout_sec

    @property
    def provider(self) -> str:
        return "openai"

    @property
    def model(self) -> str:
        return self._model

    @property
    def capabilities(self) -> STTCapabilities:
        return STTCapabilities(
            input_mode=STTInputMode.REALTIME,
            emits_interim_transcripts=True,
            persistent_connection=True,
        )

    def stream(self, *, source_id: str) -> STTStreamBase:
        if not source_id:
            raise ValueError("OpenAI STT source_id cannot be empty")

        api_key = self._api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI STT")

        return OpenAIRealtimeSTTStream(
            source_id=source_id,
            model=self._model,
            language=self._language,
            delay=self._delay,
            api_key=api_key,
            base_url=self._base_url,
            safety_identifier=self._safety_identifier,
            queue_size=self._queue_size,
            connect_timeout_sec=self._connect_timeout_sec,
            drain_timeout_sec=self._drain_timeout_sec,
        )


class OpenAIRealtimeSTTStream(STTStreamBase):
    def __init__(
        self,
        *,
        source_id: str,
        model: str,
        language: str | None,
        delay: str,
        api_key: str,
        base_url: str,
        safety_identifier: str | None,
        queue_size: int,
        connect_timeout_sec: float,
        drain_timeout_sec: float,
    ) -> None:
        self._source_id = source_id
        self._model = model
        self._language = language
        self._delay = delay
        self._api_key = api_key
        self._safety_identifier = safety_identifier
        self._connect_timeout_sec = connect_timeout_sec
        self._drain_timeout_sec = drain_timeout_sec

        parts = urlsplit(base_url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query["intent"] = "transcription"

        if parts.hostname != "api.openai.com":
            query["model"] = model

        self._url = urlunsplit(parts._replace(query=urlencode(query)))

        self._input_q: asyncio.Queue[_FrameCommand | _CommitCommand | object] = asyncio.Queue(
            maxsize=queue_size
        )
        self._event_q: asyncio.Queue[TranscriptionEvent | object] = asyncio.Queue()

        self._pending_commits: deque[str] = deque()
        self._item_to_segment: dict[str, str] = {}
        self._item_text: dict[str, str] = {}
        self._orphan_events: dict[str, list[dict[str, Any]]] = {}

        self._input_ended = False
        self._drained = asyncio.Event()
        self._accepting_input = True
        self._closed = False
        self._error: BaseException | None = None

        self._worker_task = asyncio.create_task(
            self._run(),
            name=f"openai_stt:{source_id}",
        )

    def _put_input(self, item: _FrameCommand | _CommitCommand | object) -> bool:
        if self._closed:
            return False

        try:
            self._input_q.put_nowait(item)
            return True
        except asyncio.QueueFull:
            return False

    def push_frame(self, frame: AudioFrame, *, segment_id: str) -> bool:
        if not self._accepting_input or self._closed:
            return False
        if not segment_id:
            raise ValueError("STT audio frame requires a segment_id")
        if frame.sample_format != AudioSampleFormat.PCM_S16LE:
            raise ValueError(
                f"OpenAI STT requires PCM_S16LE audio, got {frame.sample_format.value!r}"
            )
        if frame.num_channels != 1:
            raise ValueError(f"OpenAI STT requires mono audio, got {frame.num_channels} channels")

        return self._put_input(_FrameCommand(frame=frame, segment_id=segment_id))

    def commit_segment(self, segment_id: str) -> bool:
        if not self._accepting_input or self._closed:
            return False
        if not segment_id:
            raise ValueError("commit_segment requires a segment_id")

        return self._put_input(_CommitCommand(segment_id=segment_id))

    def flush(self) -> bool:
        return self._put_input(_FLUSH)

    def end_input(self) -> bool:
        if not self._accepting_input or self._closed:
            return False
        if not self._put_input(_END_INPUT):
            return False

        self._accepting_input = False
        return True

    def __aiter__(self):
        return self._iterate_events()

    async def _iterate_events(self):
        while True:
            item = await self._event_q.get()

            if item is _END_EVENTS:
                if self._error is not None:
                    raise RuntimeError(
                        f"OpenAI STT stream failed source_id={self._source_id!r}"
                    ) from self._error
                return

            yield item

    def _headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._api_key}"}

        if self._safety_identifier:
            headers["OpenAI-Safety-Identifier"] = self._safety_identifier

        return headers

    def _session_update(self) -> dict[str, Any]:
        transcription: dict[str, Any] = {
            "model": self._model,
            "delay": self._delay,
        }

        if self._language:
            transcription["language"] = self._language

        return {
            "type": "session.update",
            "session": {
                "type": "transcription",
                "audio": {
                    "input": {
                        "format": {
                            "type": "audio/pcm",
                            "rate": _TARGET_SAMPLE_RATE,
                        },
                        "transcription": transcription,
                    }
                },
            },
        }

    @staticmethod
    def _pcm_bytes(samples: np.ndarray) -> bytes:
        if samples.size == 0:
            return b""

        return np.asarray(samples, dtype="<i2").tobytes()

    async def _send_pcm(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        pcm16_bytes: bytes,
    ) -> bool:
        if not pcm16_bytes:
            return False

        await ws.send_json(
            {
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(pcm16_bytes).decode("ascii"),
            }
        )
        return True

    async def _send_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        current_segment_id: str | None = None
        current_sample_rate: int | None = None
        resampler: soxr.ResampleStream | None = None
        sent_audio = False

        def reset_segment() -> None:
            nonlocal current_segment_id, current_sample_rate, resampler, sent_audio

            current_segment_id = None
            current_sample_rate = None
            resampler = None
            sent_audio = False

        async def commit_current() -> None:
            nonlocal sent_audio

            if current_segment_id is None:
                return

            if resampler is not None:
                tail = resampler.resample_chunk(
                    np.empty(0, dtype=np.int16),
                    last=True,
                )
                sent_audio = (
                    await self._send_pcm(
                        ws,
                        self._pcm_bytes(tail),
                    )
                    or sent_audio
                )

            if not sent_audio:
                self._event_q.put_nowait(
                    TranscriptionEvent(
                        type=TranscriptionEventType.ERROR,
                        source_id=self._source_id,
                        segment_id=current_segment_id,
                        provider="openai",
                        model=self._model,
                        reason="Cannot commit an empty STT audio segment",
                    )
                )
                reset_segment()
                return

            self._pending_commits.append(current_segment_id)
            self._drained.clear()
            await ws.send_json({"type": "input_audio_buffer.commit"})
            reset_segment()

        while True:
            command = await self._input_q.get()

            if command is _FLUSH:
                if current_segment_id is not None:
                    await ws.send_json({"type": "input_audio_buffer.clear"})
                    reset_segment()
                continue

            if command is _END_INPUT:
                await commit_current()
                self._input_ended = True
                self._update_drained()
                return

            if isinstance(command, _CommitCommand):
                if current_segment_id is None:
                    continue

                if command.segment_id != current_segment_id:
                    raise RuntimeError(
                        "STT segment commit order mismatch: "
                        f"active={current_segment_id!r}, "
                        f"committed={command.segment_id!r}"
                    )

                await commit_current()
                continue

            if not isinstance(command, _FrameCommand):
                continue

            frame = command.frame

            if current_segment_id is None:
                current_segment_id = command.segment_id
                current_sample_rate = frame.sample_rate

                if frame.sample_rate != _TARGET_SAMPLE_RATE:
                    resampler = soxr.ResampleStream(
                        frame.sample_rate,
                        _TARGET_SAMPLE_RATE,
                        1,
                        dtype="int16",
                        quality="LQ",
                    )

            elif command.segment_id != current_segment_id:
                raise RuntimeError(
                    "Received a new STT segment before the current segment was committed: "
                    f"active={current_segment_id!r}, incoming={command.segment_id!r}"
                )

            elif frame.sample_rate != current_sample_rate:
                raise RuntimeError(
                    "STT input sample rate changed inside one segment: "
                    f"expected={current_sample_rate}, actual={frame.sample_rate}"
                )

            samples = np.frombuffer(frame.data, dtype="<i2")

            if resampler is not None:
                samples = resampler.resample_chunk(samples, last=False)

            sent_audio = (
                await self._send_pcm(
                    ws,
                    self._pcm_bytes(samples),
                )
                or sent_audio
            )

    def _update_drained(self) -> None:
        if self._input_ended and not self._pending_commits and not self._item_to_segment:
            self._drained.set()

    async def _emit_item_event(
        self,
        item_id: str,
        event: dict[str, Any],
    ) -> None:
        segment_id = self._item_to_segment.get(item_id)

        if segment_id is None:
            self._orphan_events.setdefault(item_id, []).append(event)
            return

        event_type = event.get("type")

        if event_type == "conversation.item.input_audio_transcription.delta":
            delta = str(event.get("delta") or "")
            text = self._item_text.get(item_id, "") + delta
            self._item_text[item_id] = text

            self._event_q.put_nowait(
                TranscriptionEvent(
                    type=TranscriptionEventType.INTERIM_TRANSCRIPT,
                    source_id=self._source_id,
                    segment_id=segment_id,
                    text=text,
                    language=self._language,
                    provider="openai",
                    model=self._model,
                )
            )
            return

        if event_type == "conversation.item.input_audio_transcription.failed":
            error = event.get("error") or {}
            reason = str(error.get("message") or error or "OpenAI transcription failed")

            self._event_q.put_nowait(
                TranscriptionEvent(
                    type=TranscriptionEventType.ERROR,
                    source_id=self._source_id,
                    segment_id=segment_id,
                    provider="openai",
                    model=self._model,
                    reason=reason,
                )
            )

            self._item_to_segment.pop(item_id, None)
            self._item_text.pop(item_id, None)
            self._update_drained()
            return

        if event_type != "conversation.item.input_audio_transcription.completed":
            return

        text = str(event.get("transcript") or self._item_text.get(item_id, ""))
        self._event_q.put_nowait(
            TranscriptionEvent(
                type=TranscriptionEventType.FINAL_TRANSCRIPT,
                source_id=self._source_id,
                segment_id=segment_id,
                text=text,
                language=self._language,
                provider="openai",
                model=self._model,
            )
        )

        self._item_to_segment.pop(item_id, None)
        self._item_text.pop(item_id, None)
        self._update_drained()

    async def _handle_server_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")

        if event_type == "input_audio_buffer.committed":
            item_id = str(event.get("item_id") or "")

            if not item_id or not self._pending_commits:
                logger.warning(
                    "OpenAI STT received unmatched commit source_id=%s item_id=%s",
                    self._source_id,
                    item_id,
                )
                return

            self._item_to_segment[item_id] = self._pending_commits.popleft()

            for orphan in self._orphan_events.pop(item_id, []):
                await self._emit_item_event(item_id, orphan)

            self._update_drained()
            return

        if event_type in {
            "conversation.item.input_audio_transcription.delta",
            "conversation.item.input_audio_transcription.completed",
            "conversation.item.input_audio_transcription.failed",
        }:
            item_id = str(event.get("item_id") or "")

            if item_id:
                await self._emit_item_event(item_id, event)

            return

        if event_type != "error":
            return

        error = event.get("error") or {}
        raise RuntimeError(str(error.get("message") or error or "OpenAI realtime STT error"))

    async def _receive_loop(
        self,
        ws: aiohttp.ClientWebSocketResponse,
    ) -> None:
        async for message in ws:
            if message.type == aiohttp.WSMsgType.TEXT:
                await self._handle_server_event(json.loads(message.data))
            elif message.type == aiohttp.WSMsgType.ERROR:
                raise RuntimeError("OpenAI realtime WebSocket failed") from ws.exception()
            elif message.type in {
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.CLOSING,
            }:
                return

        error = ws.exception()
        if error is not None:
            raise RuntimeError("OpenAI realtime WebSocket closed with an error") from error

    async def _run(self) -> None:
        sender: asyncio.Task[None] | None = None
        receiver: asyncio.Task[None] | None = None

        try:
            timeout = aiohttp.ClientTimeout(total=None)

            async with aiohttp.ClientSession(timeout=timeout) as session:
                ws = await asyncio.wait_for(
                    session.ws_connect(
                        self._url,
                        headers=self._headers(),
                        heartbeat=20.0,
                    ),
                    timeout=self._connect_timeout_sec,
                )

                try:
                    await ws.send_json(self._session_update())

                    sender = asyncio.create_task(
                        self._send_loop(ws),
                        name=f"openai_stt_sender:{self._source_id}",
                    )
                    receiver = asyncio.create_task(
                        self._receive_loop(ws),
                        name=f"openai_stt_receiver:{self._source_id}",
                    )

                    done, _ = await asyncio.wait(
                        (sender, receiver),
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    if receiver in done and not sender.done():
                        receiver.result()
                        raise RuntimeError(
                            "OpenAI realtime STT connection closed before input ended"
                        )

                    sender.result()

                    try:
                        await asyncio.wait_for(
                            self._drained.wait(),
                            timeout=self._drain_timeout_sec,
                        )
                    except TimeoutError:
                        logger.warning(
                            "OpenAI STT drain timed out source_id=%s pending_commits=%s pending_items=%s",
                            self._source_id,
                            len(self._pending_commits),
                            len(self._item_to_segment),
                        )

                    await ws.close()
                    await receiver

                finally:
                    for task in (sender, receiver):
                        if task is not None and not task.done():
                            task.cancel()

                    await asyncio.gather(
                        *(task for task in (sender, receiver) if task is not None),
                        return_exceptions=True,
                    )

        except asyncio.CancelledError:
            raise

        except Exception as error:
            self._error = error
            logger.exception(
                "OpenAI realtime STT stream failed source_id=%s",
                self._source_id,
            )

            self._event_q.put_nowait(
                TranscriptionEvent(
                    type=TranscriptionEventType.ERROR,
                    source_id=self._source_id,
                    segment_id="unknown",
                    provider="openai",
                    model=self._model,
                    reason=str(error),
                )
            )

        finally:
            self._closed = True
            self._accepting_input = False
            self._event_q.put_nowait(_END_EVENTS)

    async def aclose(self) -> None:
        if self._closed and self._worker_task.done():
            return

        self._accepting_input = False

        if not self._worker_task.done():
            self._worker_task.cancel()

        await asyncio.gather(self._worker_task, return_exceptions=True)
        self._closed = True
