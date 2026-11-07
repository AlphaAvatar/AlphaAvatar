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
import contextlib
import io
import json
import os
import re
import time
import wave
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextvars import ContextVar
from dataclasses import dataclass, field
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
from alphaavatar.core.log.events import log_event
from alphaavatar.core.media import AudioFrame, AudioSampleFormat

from ..log import logger
from .constants import TRANSCRIPTION_UNAVAILABLE

_FLUSH = object()
_END_INPUT = object()
_END_JOBS = object()
_END_EVENTS = object()

# The transport's own events for the request sent in this context, each first time seen:
# httpcore's trace names (``connection.connect_tcp.complete``, ``http11.send_request_body
# .complete``, ...) to ``time.monotonic_ns``. A reused connection traces no connect.
_TRACE: ContextVar[dict[str, int] | None] = ContextVar("segment_stt_trace", default=None)
# How long the rest of a response may take once the segment's outcome is out, its reading
# and closing together: read to its end, the connection is kept for the next segment; past
# this, it is given up and the next opens anew.
_TAIL_SEC = 0.25


async def _traced(request: httpx.Request) -> None:
    if (marks := _TRACE.get()) is not None:

        async def trace(name: str, info: dict[str, Any]) -> None:
            marks.setdefault(name, time.monotonic_ns())

        request.extensions["trace"] = trace


def _prepare(client: openai.AsyncOpenAI) -> None:
    """The SDK's transcription resource, which it imports on first use: about 0.1 s that
    would otherwise fall on the first segment's request, on the event loop."""
    _ = client.audio.transcriptions


# A server-sent event stream's line ends, and only these: str.splitlines (and so httpx's
# iter_lines) also breaks at U+2028, U+0085 and others, which a JSON string may hold as is.
_LINE_END = re.compile("\r\n|\r|\n")


async def _sse(text: AsyncIterator[str]) -> AsyncIterator[str]:
    """Each server-sent event's data, its ``data:`` lines joined: the body's text as the
    response decodes it (a character split across chunks whole again), split at CR, LF or
    CRLF, a leading BOM dropped, comments and other fields skipped; read to the body's end.
    An event the body ends without its blank line is still given."""
    pending, data, begun = "", [], False

    def field(line: str) -> None:
        name, _, value = line.partition(":")
        if name == "data":
            data.append(value.removeprefix(" "))

    async for chunk in text:
        if not begun:
            chunk, begun = chunk.removeprefix("\ufeff"), True
        pending += chunk
        held = pending.endswith("\r")  # Perhaps the first half of a CRLF
        *lines, pending = _LINE_END.split(pending[:-1] if held else pending)
        pending += "\r" if held else ""
        for line in lines:
            if line:
                if not line.startswith(":"):
                    field(line)
            elif data:
                yield "\n".join(data)
                data = []
    for line in _LINE_END.split(pending):
        if line and not line.startswith(":"):
            field(line)
    if data:
        yield "\n".join(data)


def _between(marks: dict[str, int], start: str, end: str) -> float | None:
    """Milliseconds from the first event named ``start`` to ``end``, by suffix: the same for
    HTTP/1.1 and HTTP/2."""
    first = next((at for name, at in marks.items() if name.endswith(start)), None)
    last = next((at for name, at in marks.items() if name.endswith(end)), None)
    return None if first is None or last is None else round((last - first) / 1e6, 3)


@dataclass(slots=True, frozen=True)
class _FrameCommand:
    frame: AudioFrame
    segment_id: str


@dataclass(slots=True, frozen=True)
class _CommitCommand:
    segment_id: str


@dataclass(slots=True)
class _SegmentBuffer:
    sample_rate: int
    pcm: bytearray = field(default_factory=bytearray)


@dataclass(slots=True, frozen=True)
class _SegmentJob:
    segment_id: str
    pcm: bytes
    sample_rate: int
    committed_ns: int = field(default_factory=time.monotonic_ns)

    @property
    def duration_sec(self) -> float:
        return len(self.pcm) / (self.sample_rate * 2)


class OpenAISegmentSTT(STTBase):
    """OpenAI transcription over completed AlphaAvatar speech segments."""

    fallback_code = TRANSCRIPTION_UNAVAILABLE

    def __init__(
        self,
        *,
        model: str = "gpt-4o-mini-transcribe",
        language: str | None = None,
        prompt: str | None = None,
        temperature: float | None = None,
        api_key: str | None = None,
        api_key_env: str = "OPENAI_API_KEY",
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
        self._api_key, self._api_key_env = api_key, api_key_env
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

        api_key = self._api_key or os.getenv(self._api_key_env)
        if self._client is None and not api_key:
            raise RuntimeError(f"{self._api_key_env} is required for OpenAI STT")

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
            # The SDK's own transport, each request's connect and exchange timed.
            http_client=openai.DefaultAsyncHttpxClient(event_hooks={"request": [_traced]}),
        )

        self._input_q: asyncio.Queue[_FrameCommand | _CommitCommand | object] = asyncio.Queue(
            maxsize=queue_size
        )
        self._job_q: asyncio.Queue[_SegmentJob | object] = asyncio.Queue(maxsize=request_queue_size)
        self._event_q: asyncio.Queue[TranscriptionEvent | object] = asyncio.Queue()
        self._retention_limit = max(32, queue_size * 4)
        self._open_segments: set[str] = set()
        self._pending_segments: set[str] = set()
        # Protect recent segment identities without keeping an unbounded session history.
        self._committed_segments: OrderedDict[str, None] = OrderedDict()

        self._accepting_input = True
        self._closed = False
        self._error: BaseException | None = None

        # Off the event loop, while the segment is still spoken.
        self._prepared = asyncio.create_task(
            asyncio.to_thread(_prepare, self._client), name=f"openai_segment_prepare:{source_id}"
        )
        self._worker_task = asyncio.create_task(self._run(), name=f"openai_segment_stt:{source_id}")

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

        if segment_id in self._committed_segments or segment_id in self._pending_segments:
            return False
        if (
            segment_id not in self._open_segments
            and len(self._open_segments) + len(self._pending_segments) >= self._input_q.maxsize
        ):
            return False
        if not self._put_input(_FrameCommand(frame=frame, segment_id=segment_id)):
            return False
        self._open_segments.add(segment_id)
        return True

    def _remember_commit(self, segment_id: str) -> None:
        self._open_segments.discard(segment_id)
        self._committed_segments[segment_id] = None
        self._committed_segments.move_to_end(segment_id)
        if len(self._committed_segments) > self._retention_limit:
            self._committed_segments.popitem(last=False)

    def commit_segment(self, segment_id: str) -> bool:
        if not segment_id:
            raise ValueError("commit_segment requires a segment_id")

        if not self._accepting_input or self._closed:
            return False
        if segment_id in self._committed_segments or segment_id in self._pending_segments:
            return True
        if (
            segment_id not in self._open_segments
            and len(self._open_segments) + len(self._pending_segments) >= self._input_q.maxsize
        ):
            return False
        if not self._put_input(_CommitCommand(segment_id=segment_id)):
            return False
        self._remember_commit(segment_id)
        self._pending_segments.add(segment_id)
        return True

    def flush(self) -> bool:
        if not self._put_input(_FLUSH):
            return False
        for segment_id in tuple(self._open_segments):
            self._remember_commit(segment_id)
        return True

    def end_input(self) -> bool:
        if not self._accepting_input or self._closed:
            return False
        if not self._put_input(_END_INPUT):
            return False

        for segment_id in tuple(self._open_segments):
            self._remember_commit(segment_id)
            self._pending_segments.add(segment_id)
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

    def _emit_error(
        self, segment_id: str, reason: str, *, reason_code: str = "provider_error"
    ) -> None:
        self._pending_segments.discard(segment_id)
        if segment_id != "unknown":
            self._remember_commit(segment_id)
        self._event_q.put_nowait(
            TranscriptionEvent(
                type=TranscriptionEventType.ERROR,
                source_id=self._source_id,
                segment_id=segment_id,
                provider="openai",
                model=self._model,
                reason=reason,
                reason_code=reason_code,
            )
        )

    def _emit_transcript(
        self, *, event_type: TranscriptionEventType, segment_id: str, text: str, duration_sec: float
    ) -> None:
        if event_type == TranscriptionEventType.FINAL_TRANSCRIPT:
            self._pending_segments.discard(segment_id)
            self._remember_commit(segment_id)
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
        segments: dict[str, _SegmentBuffer] = {}

        def commit(segment_id: str) -> None:
            state = segments.pop(segment_id, None)
            if state is None:
                self._emit_error(
                    segment_id,
                    "STT segment committed without buffered audio",
                    reason_code="missing_audio",
                )
                return

            if not state.pcm:
                self._emit_error(
                    segment_id,
                    "Cannot commit an empty STT audio segment",
                    reason_code="empty_segment",
                )
                return

            job = _SegmentJob(
                segment_id=segment_id, pcm=bytes(state.pcm), sample_rate=state.sample_rate
            )

            try:
                self._job_q.put_nowait(job)
            except asyncio.QueueFull:
                self._emit_error(
                    segment_id,
                    "OpenAI STT request queue is full; segment discarded",
                    reason_code="request_queue_full",
                )

        while True:
            command = await self._input_q.get()

            if command is _FLUSH:
                for segment_id in segments:
                    self._emit_error(
                        segment_id, "Buffered STT input was flushed", reason_code="input_flushed"
                    )
                segments.clear()
                continue

            if command is _END_INPUT:
                for segment_id in tuple(segments):
                    commit(segment_id)

                await self._job_q.put(_END_JOBS)
                return

            if isinstance(command, _CommitCommand):
                commit(command.segment_id)
                continue

            if not isinstance(command, _FrameCommand):
                continue

            frame = command.frame
            state = segments.get(command.segment_id)

            if state is None:
                state = _SegmentBuffer(sample_rate=frame.sample_rate)
                segments[command.segment_id] = state
            elif frame.sample_rate != state.sample_rate:
                raise RuntimeError(
                    f"STT input sample rate changed inside segment "
                    f"{command.segment_id!r}: expected={state.sample_rate}, "
                    f"actual={frame.sample_rate}"
                )

            state.pcm.extend(frame.data)

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
            "file": ("segment.wav", self._wav_bytes(job), "audio/wav"),
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

    def _emit_final(self, job: _SegmentJob, text: object, done: dict[str, Any]) -> None:
        """The segment's final, or invalid_final when it has no text: ``done`` marks which
        went out, and when a valid one did."""
        if not isinstance(text, str):
            done["outcome"] = "invalid_final"
            self._emit_error(
                job.segment_id,
                "OpenAI transcription final has no text field",
                reason_code="invalid_final",
            )
            return
        done["final"], done["outcome"] = time.monotonic_ns(), "final"
        self._emit_transcript(
            event_type=TranscriptionEventType.FINAL_TRANSCRIPT,
            segment_id=job.segment_id,
            text=text,
            duration_sec=job.duration_sec,
        )

    async def _exchange(
        self, job: _SegmentJob, marks: dict[str, int], done: dict[str, Any]
    ) -> None:
        # The raw response, read here to the body's end: the SDK's own stream closes it at
        # ``data: [DONE]``, before the chunked body ends, and the connection goes with it.
        request = self._client.audio.transcriptions.with_streaming_response.create(
            **self._request_kwargs(job)
        )
        token = _TRACE.set(marks)
        try:
            response = await request.__aenter__()  # Closed below, within the tail's bound
        finally:
            _TRACE.reset(token)

        settled = closed = False  # The segment's outcome is out; the response is released
        bound: float | None = None  # When the tail's reading and closing must be done
        text, last_interim_at = "", 0.0

        def settle(tail: asyncio.Timeout) -> None:
            nonlocal settled, bound
            settled, bound = True, asyncio.get_running_loop().time() + _TAIL_SEC
            tail.reschedule(bound)

        try:
            # The outcome goes out once, as it arrives; the rest of the body is then read and
            # the response closed within _TAIL_SEC. A tail that fails, stalls or will not
            # close costs that connection only.
            async with asyncio.timeout(None) as tail:
                if "text/event-stream" not in response.headers.get("content-type", ""):
                    # whisper-1 ignores stream=True and answers with the whole transcript.
                    body = await response.json()
                    final_text = body.get("text") if isinstance(body, dict) else None
                    done["first"] = time.monotonic_ns()
                    self._emit_final(job, final_text, done)
                    settle(tail)
                else:
                    async for data in _sse(response.iter_text()):
                        if settled:
                            continue  # Past the outcome: read for the connection, not handled
                        if data == "[DONE]":
                            done["outcome"] = "missing_final"
                            self._emit_error(
                                job.segment_id,
                                "OpenAI transcription stream closed without a final result",
                                reason_code="missing_final",
                            )
                            settle(tail)
                            continue

                        done.setdefault("first", time.monotonic_ns())
                        event = json.loads(data)
                        if isinstance(event, dict) and event.get("error"):
                            error = event["error"]
                            message = error.get("message") if isinstance(error, dict) else None
                            raise openai.APIError(
                                message
                                if isinstance(message, str) and message
                                else "An error occurred during streaming",
                                response.http_response.request,
                                body=error,
                            )
                        event_type = event.get("type") if isinstance(event, dict) else None

                        if event_type == "transcript.text.delta":
                            text += str(event.get("delta", ""))
                            now = time.monotonic()

                            if text and now - last_interim_at >= self._interim_interval_sec:
                                self._emit_transcript(
                                    event_type=TranscriptionEventType.INTERIM_TRANSCRIPT,
                                    segment_id=job.segment_id,
                                    text=text,
                                    duration_sec=job.duration_sec,
                                )
                                last_interim_at = now

                        elif event_type == "transcript.text.done":
                            self._emit_final(job, event.get("text"), done)
                            settle(tail)

                await response.close()
                closed = True
        except Exception:
            if not settled:
                raise
            logger.debug(
                "OpenAI STT response after its outcome was not read to its end", exc_info=True
            )
        finally:
            if not closed:
                # Cut short by a failure, a cancellation or the bound: closed within the same
                # bound, or one of its own when the outcome never went out.
                with contextlib.suppress(Exception):
                    loop = asyncio.get_running_loop()
                    async with asyncio.timeout_at(bound or loop.time() + _TAIL_SEC):
                        await response.close()

        if not settled:
            done["outcome"] = "missing_final"
            self._emit_error(
                job.segment_id,
                "OpenAI transcription stream closed without a final result",
                reason_code="missing_final",
            )

    async def _transcribe(self, job: _SegmentJob) -> None:
        started, marks, done = time.monotonic_ns(), {}, {}
        try:
            await self._exchange(job, marks, done)
        finally:
            # Where the segment's time went: its wait in the request queue, the connection
            # (none when reused), the upload, the server's answer and its stream to the final.
            # Reuse is known from a traced request only: a client of the caller's own, or a
            # request that failed before the transport sent it, traces nothing.
            sent = any(name.endswith("send_request_headers.started") for name in marks)
            opened = any(name.endswith("connect_tcp.started") for name in marks)
            answered = next(
                (at for n, at in marks.items() if n.endswith("receive_response_headers.complete")),
                None,
            )
            log_event(
                logger,
                "stt.request",
                segment_id=job.segment_id,
                outcome=done.get("outcome", "no_final"),
                queue_ms=round((started - job.committed_ns) / 1e6, 3),
                reused=False if opened else True if sent else None,
                connect_ms=_between(marks, "connect_tcp.started", "connect_tcp.complete"),
                tls_ms=_between(marks, "start_tls.started", "start_tls.complete"),
                upload_ms=_between(
                    marks, "send_request_headers.started", "send_request_body.complete"
                ),
                wait_ms=_between(
                    marks, "send_request_body.complete", "receive_response_headers.complete"
                ),
                first_event_ms=(
                    None
                    if answered is None or "first" not in done
                    else round((done["first"] - answered) / 1e6, 3)
                ),
                final_ms=(
                    None
                    if answered is None or "final" not in done
                    else round((done["final"] - answered) / 1e6, 3)
                ),
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
        # A request waits for the SDK's preparation rather than import it on the event loop;
        # a preparation that failed leaves the import to the request, as without it.
        await asyncio.gather(self._prepared, return_exceptions=True)
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
                reason_code = (
                    "request_timeout"
                    if isinstance(error, openai.APITimeoutError)
                    else "connection_error"
                    if isinstance(error, openai.APIConnectionError)
                    else "provider_error"
                )
                self._emit_error(item.segment_id, reason, reason_code=reason_code)

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
                self._ingest_loop(), name=f"openai_segment_ingest:{self._source_id}"
            )
            request_task = asyncio.create_task(
                self._request_loop(), name=f"openai_segment_requests:{self._source_id}"
            )

            await asyncio.gather(ingest_task, request_task)

        except asyncio.CancelledError:
            raise

        except Exception as error:
            self._error = error

            logger.exception("OpenAI segment STT stream failed source_id=%s", self._source_id)

            self._emit_error("unknown", str(error), reason_code="stream_error")

        finally:
            for task in (ingest_task, request_task, self._prepared):
                if task is not None and not task.done():
                    task.cancel()

            await asyncio.gather(
                *(task for task in (ingest_task, request_task, self._prepared) if task is not None),
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

        await asyncio.gather(self._worker_task, return_exceptions=True)

        self._closed = True
