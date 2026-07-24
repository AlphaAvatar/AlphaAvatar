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
import io
import os
import time
import wave
from dataclasses import dataclass
from typing import Any

import httpx
import openai

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

_FLUSH = object()
_END_INPUT = object()
_END_JOBS = object()
_END_EVENTS = object()


@dataclass(slots=True, frozen=True)
class _FrameCommand:
    frame: AudioFrame
    segment_id: str


@dataclass(slots=True, frozen=True)
class _CommitCommand:
    segment_id: str


@dataclass(slots=True, frozen=True)
class _SegmentJob:
    segment_id: str
    pcm: bytes
    sample_rate: int

    @property
    def duration_sec(self) -> float:
        return len(self.pcm) / (self.sample_rate * 2)


class OpenAISegmentSTT(STTBase):
    """OpenAI transcription over completed AlphaAvatar speech segments."""

    def __init__(
        self,
        *,
        model: str = "gpt-4o-mini-transcribe",
        language: str | None = None,
        prompt: str | None = None,
        temperature: float | None = None,
        api_key: str | None = None,
        base_url: str = "https://api.openai.com/v1",
        client: openai.AsyncOpenAI | None = None,
        queue_size: int = 256,
        request_queue_size: int = 8,
        request_timeout_sec: float = 30.0,
        interim_interval_sec: float = 0.1,
    ) -> None:
        if not model:
            raise ValueError("OpenAI STT model cannot be empty")
        if temperature is not None and not 0.0 <= temperature <= 1.0:
            raise ValueError("temperature must be between 0 and 1")
        if queue_size <= 0 or request_queue_size <= 0:
            raise ValueError("STT queue sizes must be positive")
        if request_timeout_sec <= 0 or interim_interval_sec < 0:
            raise ValueError("STT timeouts and intervals must be valid")

        self._model = model
        self._language = language
        self._prompt = prompt
        self._temperature = temperature
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._queue_size = queue_size
        self._request_queue_size = request_queue_size
        self._request_timeout_sec = request_timeout_sec
        self._interim_interval_sec = interim_interval_sec

    @property
    def provider(self) -> str:
        return "openai"

    @property
    def model(self) -> str:
        return self._model

    @property
    def capabilities(self) -> STTCapabilities:
        return STTCapabilities(
            input_mode=STTInputMode.SEGMENT,
            emits_interim_transcripts=self._model != "whisper-1",
            persistent_connection=False,
        )

    def stream(self, *, source_id: str) -> STTStreamBase:
        if not source_id:
            raise ValueError("OpenAI STT source_id cannot be empty")

        api_key = self._api_key or os.getenv("OPENAI_API_KEY")
        if self._client is None and not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI STT")

        return OpenAISegmentSTTStream(
            source_id=source_id,
            model=self._model,
            language=self._language,
            prompt=self._prompt,
            temperature=self._temperature,
            api_key=api_key,
            base_url=self._base_url,
            client=self._client,
            queue_size=self._queue_size,
            request_queue_size=self._request_queue_size,
            request_timeout_sec=self._request_timeout_sec,
            interim_interval_sec=self._interim_interval_sec,
        )


class OpenAISegmentSTTStream(STTStreamBase):
    def __init__(
        self,
        *,
        source_id: str,
        model: str,
        language: str | None,
        prompt: str | None,
        temperature: float | None,
        api_key: str | None,
        base_url: str,
        client: openai.AsyncOpenAI | None,
        queue_size: int,
        request_queue_size: int,
        request_timeout_sec: float,
        interim_interval_sec: float,
    ) -> None:
        self._source_id = source_id
        self._model = model
        self._language = language
        self._prompt = prompt
        self._temperature = temperature
        self._request_timeout_sec = request_timeout_sec
        self._interim_interval_sec = interim_interval_sec

        self._owns_client = client is None
        self._client = client or openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            max_retries=0,
            timeout=httpx.Timeout(request_timeout_sec),
        )

        self._input_q: asyncio.Queue[_FrameCommand | _CommitCommand | object] = asyncio.Queue(
            maxsize=queue_size
        )
        self._job_q: asyncio.Queue[_SegmentJob | object] = asyncio.Queue(maxsize=request_queue_size)
        self._event_q: asyncio.Queue[TranscriptionEvent | object] = asyncio.Queue()

        self._accepting_input = True
        self._closed = False
        self._error: BaseException | None = None

        self._worker_task = asyncio.create_task(
            self._run(),
            name=f"openai_segment_stt:{source_id}",
        )

    def _put_input(self, item: _FrameCommand | _CommitCommand | object) -> bool:
        if not self._accepting_input or self._closed:
            return False

        try:
            self._input_q.put_nowait(item)
            return True
        except asyncio.QueueFull:
            return False

    def push_frame(self, frame: AudioFrame, *, segment_id: str) -> bool:
        if not segment_id:
            raise ValueError("STT audio frame requires a segment_id")
        if frame.sample_format != AudioSampleFormat.PCM_S16LE:
            raise ValueError(
                f"OpenAI STT requires PCM_S16LE audio, got {frame.sample_format.value!r}"
            )
        if frame.num_channels != 1:
            raise ValueError(f"OpenAI STT requires mono audio, got {frame.num_channels} channels")

        return self._put_input(
            _FrameCommand(
                frame=frame,
                segment_id=segment_id,
            )
        )

    def commit_segment(self, segment_id: str) -> bool:
        if not segment_id:
            raise ValueError("commit_segment requires a segment_id")

        return self._put_input(
            _CommitCommand(
                segment_id=segment_id,
            )
        )

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

    def _emit_error(self, segment_id: str, reason: str) -> None:
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

    def _emit_transcript(
        self,
        *,
        event_type: TranscriptionEventType,
        segment_id: str,
        text: str,
        duration_sec: float,
    ) -> None:
        self._event_q.put_nowait(
            TranscriptionEvent(
                type=event_type,
                source_id=self._source_id,
                segment_id=segment_id,
                text=text,
                language=self._language,
                provider="openai",
                model=self._model,
                start_time=0.0,
                end_time=duration_sec,
            )
        )

    async def _ingest_loop(self) -> None:
        current_segment_id: str | None = None
        current_sample_rate: int | None = None
        current_pcm = bytearray()

        def reset() -> None:
            nonlocal current_segment_id, current_sample_rate

            current_segment_id = None
            current_sample_rate = None
            current_pcm.clear()

        def commit_current(expected_segment_id: str | None = None) -> None:
            if current_segment_id is None:
                return

            if expected_segment_id is not None and expected_segment_id != current_segment_id:
                raise RuntimeError(
                    "STT segment commit order mismatch: "
                    f"active={current_segment_id!r}, "
                    f"committed={expected_segment_id!r}"
                )

            if not current_pcm or current_sample_rate is None:
                self._emit_error(
                    current_segment_id,
                    "Cannot commit an empty STT audio segment",
                )
                reset()
                return

            job = _SegmentJob(
                segment_id=current_segment_id,
                pcm=bytes(current_pcm),
                sample_rate=current_sample_rate,
            )

            try:
                self._job_q.put_nowait(job)
            except asyncio.QueueFull:
                self._emit_error(
                    current_segment_id,
                    "OpenAI STT request queue is full; segment discarded",
                )

            reset()

        while True:
            command = await self._input_q.get()

            if command is _FLUSH:
                reset()
                continue

            if command is _END_INPUT:
                commit_current()
                await self._job_q.put(_END_JOBS)
                return

            if isinstance(command, _CommitCommand):
                commit_current(command.segment_id)
                continue

            if not isinstance(command, _FrameCommand):
                continue

            frame = command.frame

            if current_segment_id is None:
                current_segment_id = command.segment_id
                current_sample_rate = frame.sample_rate

            elif command.segment_id != current_segment_id:
                raise RuntimeError(
                    "Received a new STT segment before the current segment "
                    "was committed: "
                    f"active={current_segment_id!r}, "
                    f"incoming={command.segment_id!r}"
                )

            elif frame.sample_rate != current_sample_rate:
                raise RuntimeError(
                    "STT input sample rate changed inside one segment: "
                    f"expected={current_sample_rate}, "
                    f"actual={frame.sample_rate}"
                )

            current_pcm.extend(frame.data)

    @staticmethod
    def _wav_bytes(job: _SegmentJob) -> bytes:
        output = io.BytesIO()

        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(job.sample_rate)
            wav.writeframes(job.pcm)

        return output.getvalue()

    def _request_kwargs(self, job: _SegmentJob) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "file": (
                "segment.wav",
                self._wav_bytes(job),
                "audio/wav",
            ),
            "model": self._model,
            "response_format": "json",
            "stream": True,
        }

        if self._language:
            kwargs["language"] = self._language

        if self._prompt:
            kwargs["prompt"] = self._prompt

        if self._temperature is not None:
            kwargs["temperature"] = self._temperature

        return kwargs

    async def _transcribe(self, job: _SegmentJob) -> None:
        response = await self._client.audio.transcriptions.create(**self._request_kwargs(job))

        # whisper-1 ignores stream=True and returns a complete response.
        if not hasattr(response, "__aiter__"):
            self._emit_transcript(
                event_type=TranscriptionEventType.FINAL_TRANSCRIPT,
                segment_id=job.segment_id,
                text=str(getattr(response, "text", "")),
                duration_sec=job.duration_sec,
            )
            return

        text = ""
        final_emitted = False
        last_interim_at = 0.0

        async for event in response:
            event_type = getattr(event, "type", "")

            if event_type == "transcript.text.delta":
                text += str(getattr(event, "delta", ""))
                now = time.monotonic()

                if text and now - last_interim_at >= self._interim_interval_sec:
                    self._emit_transcript(
                        event_type=TranscriptionEventType.INTERIM_TRANSCRIPT,
                        segment_id=job.segment_id,
                        text=text,
                        duration_sec=job.duration_sec,
                    )
                    last_interim_at = now

                continue

            if event_type == "transcript.text.done":
                text = str(getattr(event, "text", "") or text)

                self._emit_transcript(
                    event_type=TranscriptionEventType.FINAL_TRANSCRIPT,
                    segment_id=job.segment_id,
                    text=text,
                    duration_sec=job.duration_sec,
                )
                final_emitted = True

        if text and not final_emitted:
            self._emit_transcript(
                event_type=TranscriptionEventType.FINAL_TRANSCRIPT,
                segment_id=job.segment_id,
                text=text,
                duration_sec=job.duration_sec,
            )

    @staticmethod
    def _api_error_reason(error: BaseException) -> str:
        if isinstance(error, openai.APIStatusError):
            return f"{error.message} status_code={error.status_code} request_id={error.request_id}"

        if isinstance(error, openai.APITimeoutError):
            return "OpenAI STT request timed out"

        if isinstance(error, openai.APIConnectionError):
            return f"OpenAI STT connection failed: {error}"

        return str(error) or error.__class__.__name__

    async def _request_loop(self) -> None:
        while True:
            item = await self._job_q.get()

            if item is _END_JOBS:
                return

            if not isinstance(item, _SegmentJob):
                continue

            try:
                await self._transcribe(item)

            except asyncio.CancelledError:
                raise

            except Exception as error:
                reason = self._api_error_reason(error)
                self._emit_error(
                    item.segment_id,
                    reason,
                )

                if isinstance(
                    error,
                    openai.APIStatusError | openai.APITimeoutError | openai.APIConnectionError,
                ):
                    logger.warning(
                        "OpenAI segment STT request failed source_id=%s segment_id=%s reason=%s",
                        self._source_id,
                        item.segment_id,
                        reason,
                    )
                else:
                    logger.exception(
                        "OpenAI segment STT request failed source_id=%s segment_id=%s",
                        self._source_id,
                        item.segment_id,
                    )

    async def _run(self) -> None:
        ingest_task: asyncio.Task[None] | None = None
        request_task: asyncio.Task[None] | None = None

        try:
            ingest_task = asyncio.create_task(
                self._ingest_loop(),
                name=f"openai_segment_ingest:{self._source_id}",
            )
            request_task = asyncio.create_task(
                self._request_loop(),
                name=f"openai_segment_requests:{self._source_id}",
            )

            await asyncio.gather(
                ingest_task,
                request_task,
            )

        except asyncio.CancelledError:
            raise

        except Exception as error:
            self._error = error

            logger.exception(
                "OpenAI segment STT stream failed source_id=%s",
                self._source_id,
            )

            self._emit_error(
                "unknown",
                str(error),
            )

        finally:
            for task in (ingest_task, request_task):
                if task is not None and not task.done():
                    task.cancel()

            await asyncio.gather(
                *(task for task in (ingest_task, request_task) if task is not None),
                return_exceptions=True,
            )

            if self._owns_client:
                await self._client.close()

            self._closed = True
            self._accepting_input = False
            self._event_q.put_nowait(_END_EVENTS)

    async def aclose(self) -> None:
        if self._closed and self._worker_task.done():
            return

        self._accepting_input = False

        if not self._worker_task.done():
            self._worker_task.cancel()

        await asyncio.gather(
            self._worker_task,
            return_exceptions=True,
        )

        self._closed = True
