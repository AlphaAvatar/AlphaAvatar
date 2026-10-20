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
from abc import abstractmethod
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from functools import partial
from math import isfinite
from urllib.parse import urlsplit
from uuid import uuid4

import aiohttp

from alphaavatar.agents.avatar.voice import TTSBase, TTSStreamBase
from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.media import AudioFrame

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class PCMSettings:
    # Bound HTTP waits and retry backoff; local consumer waits do not use this budget.
    timeout: float = 30.0
    first_audio_timeout: float = 2.5
    read_timeout: float = 10.0
    max_retries: int = 1
    retry_interval: float = 0.1
    frame_size_ms: int = 20
    # Read ahead while the preceding segment plays; this is a cap, never a fill gate.
    queue_frames: int = 64
    max_streams: int = 4
    max_audio_seconds: float = 120.0

    def __post_init__(self) -> None:
        for name, maximum in (("frame_size_ms", 100), ("queue_frames", 128), ("max_streams", 32)):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f"{name} must be an integer in 1..{maximum}")
        if type(self.max_retries) is not int or not 0 <= self.max_retries <= 3:
            raise ValueError("max_retries must be an integer in 0..3")
        for name in (
            "timeout",
            "first_audio_timeout",
            "read_timeout",
            "retry_interval",
            "max_audio_seconds",
        ):
            value = getattr(self, name)
            if type(value) not in (int, float) or not isfinite(value) or not 0 < value <= 3600:
                raise ValueError(f"{name} must be finite and in (0, 3600]")


class TTSHTTPError(RuntimeError):
    """Remote status without credentials, input text, URLs or response bodies."""

    def __init__(self, provider: str, status: int, *, retry_after: float | None = None) -> None:
        self.provider, self.status, self.retry_after = provider, status, retry_after
        super().__init__(f"{provider} TTS request failed with HTTP {status}")


class TTSTimeoutError(TimeoutError):
    def __init__(self, provider: str, phase: str) -> None:
        self.provider, self.phase = provider, phase
        super().__init__(f"{provider} TTS timed out during {phase}")


class TTSTransportError(RuntimeError):
    def __init__(self, provider: str, phase: str, error_type: str) -> None:
        self.provider, self.phase, self.error_type = provider, phase, error_type
        super().__init__(f"{provider} TTS transport failed during {phase}: {error_type}")


class PCMHTTPProvider(TTSBase):
    """Shared bounded HTTP/PCM transport; vendors own URLs and request schemas."""

    def __init__(
        self, *, provider: str, url: str, api_key: str, sample_rate: int, settings: PCMSettings
    ) -> None:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in ("https", "http")
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("TTS URL must omit credentials, query and fragment")
        if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("Remote TTS endpoints require HTTPS")
        if not isinstance(api_key, str) or not api_key.strip() or any(c.isspace() for c in api_key):
            raise ValueError(f"{provider} TTS requires a nonempty API key without whitespace")
        if type(sample_rate) is not int or sample_rate <= 0:
            raise ValueError("TTS sample rate must be a positive integer")
        if sample_rate * settings.frame_size_ms % 1000:
            raise ValueError("TTS frame duration must contain a whole number of PCM samples")

        self._provider, self._url, self._api_key = provider, url, api_key
        self._sample_rate, self._settings = sample_rate, settings
        self._frame_bytes = sample_rate * settings.frame_size_ms // 1000 * 2
        self._max_audio_bytes = int(sample_rate * settings.max_audio_seconds) * 2

        self._streams: set[_PCMStream] = set()
        self._client: aiohttp.ClientSession | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._close_task: asyncio.Task[None] | None = None

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def num_channels(self) -> int:
        return 1

    @staticmethod
    def _observe(task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()

    def _check_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise RuntimeError("TTS providers cannot be shared across event loops")

    @abstractmethod
    def _payload(self, text: str) -> dict[str, str]: ...

    def synthesize(self, text: str) -> TTSStreamBase:
        self._check_loop()
        if self._close_task is not None:
            raise RuntimeError("TTS provider is closing or closed")
        if not isinstance(text, str) or not text.strip() or len(text) > 4096:
            raise ValueError("TTS input must contain 1..4096 characters and non-whitespace text")
        if len(self._streams) >= self._settings.max_streams:
            raise RuntimeError("TTS synthesis capacity exhausted")

        # Own the request before its first await, but do not start HTTP until it is read.
        stream = _PCMStream(self, self._payload(text))
        self._streams.add(stream)
        return stream

    def _get_client(self) -> aiohttp.ClientSession:
        if self._close_task is not None:
            raise RuntimeError("TTS provider is closing or closed")

        if self._client is None:
            # The resident stream limit also bounds concurrent connections to this endpoint.
            self._client = aiohttp.ClientSession(
                # Explicit read deadlines below pause while the bounded PCM queue is full.
                timeout=aiohttp.ClientTimeout(
                    total=None, sock_connect=self._settings.first_audio_timeout, sock_read=None
                ),
                auto_decompress=False,
                read_bufsize=max(4096, self._frame_bytes * self._settings.queue_frames),
            )
        return self._client

    @staticmethod
    def _retry_after(value: str | None) -> float | None:
        """Respect a bounded, parsed server hint; never log its untrusted raw value."""
        if value is None or len(value) > 128:
            return None
        value = value.strip()
        if value.isascii() and value.isdecimal():
            return float(value)
        try:
            instant = parsedate_to_datetime(value)
            if instant.tzinfo is None:
                return None
            return max(0.0, (instant - datetime.now(UTC)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None

    async def _produce(
        self,
        payload: dict[str, str],
        emit: Callable[[AudioFrame], Awaitable[None]],
        *,
        request_id: str,
    ) -> None:
        settings, clock = self._settings, asyncio.get_running_loop().time
        remaining = settings.timeout
        emitted = received = 0
        blocked = http_wait = retry_wait = 0.0
        read_gaps = 0
        started = clock()

        async def network[T](
            operation: Callable[[], Awaitable[T]], phase: str, first_deadline: float
        ) -> T:
            nonlocal remaining, http_wait
            limit = min(
                remaining, first_deadline - clock() if not emitted else settings.read_timeout
            )
            if limit <= 0:
                raise TTSTimeoutError(self._provider, phase)
            before = clock()
            try:
                async with asyncio.timeout(limit):
                    return await operation()
            except TimeoutError:
                raise TTSTimeoutError(self._provider, phase) from None
            finally:
                waited = clock() - before
                http_wait += waited
                remaining = max(0.0, remaining - waited)

        for attempt in range(1, settings.max_retries + 2):
            phase, response = "response_headers", None
            attempt_started = clock()
            first_deadline = attempt_started + min(remaining, settings.first_audio_timeout)
            logger.debug(
                "TTS REQUEST provider=%s request_id=%s attempt=%d first_audio_timeout_ms=%.1f",
                self._provider,
                request_id,
                attempt,
                (first_deadline - attempt_started) * 1000,
            )
            try:
                response = await network(
                    partial(
                        self._get_client().post,
                        self._url,
                        json=payload,
                        allow_redirects=False,
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Accept-Encoding": "identity",
                        },
                    ),
                    phase,
                    first_deadline,
                )
                phase = "response_validation"
                if response.status != 200:
                    raise TTSHTTPError(
                        self._provider,
                        response.status,
                        retry_after=self._retry_after(response.headers.get("Retry-After")),
                    )

                logger.debug(
                    "TTS HEADERS provider=%s request_id=%s attempt=%d status=%d",
                    self._provider,
                    request_id,
                    attempt,
                    response.status,
                )
                content_type = response.headers.get("Content-Type", "")
                content_type = content_type.split(";", 1)[0].strip().lower()
                if content_type not in ("audio/pcm", "audio/x-pcm", "application/octet-stream"):
                    raise RuntimeError(f"{self._provider} TTS did not return raw PCM")
                if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                    raise RuntimeError(f"{self._provider} TTS returned encoded PCM")

                total = 0
                while True:
                    phase, last = "first_audio" if not emitted else "audio_read", False
                    read_started = clock()
                    try:
                        data = await network(
                            partial(response.content.readexactly, self._frame_bytes),
                            phase,
                            first_deadline,
                        )
                    except asyncio.IncompleteReadError as error:
                        data, last = error.partial, True

                    read_wait = clock() - read_started
                    if data and emitted and read_wait >= 0.05:
                        read_gaps += 1
                        if read_gaps <= 3:
                            logger.debug(
                                "TTS PCM GAP provider=%s request_id=%s attempt=%d "
                                "read_wait_ms=%.1f pcm_seconds_before=%.3f "
                                "measurement=provider_read_wait",
                                self._provider,
                                request_id,
                                attempt,
                                read_wait * 1000,
                                total / (2 * self.sample_rate),
                            )
                    if data:
                        phase = "pcm_validation"
                        if len(data) % 2:
                            raise RuntimeError("TTS returned an incomplete PCM sample")
                        if total == 0 and (
                            (data.startswith(b"RIFF") and data[8:12] == b"WAVE")
                            or data.startswith((b"ID3", b"OggS", b"fLaC"))
                        ):
                            raise RuntimeError("TTS returned an audio container instead of PCM")
                        total += len(data)
                        received += len(data)
                        if total > self._max_audio_bytes:
                            raise RuntimeError("TTS audio duration exceeds its limit")

                        frame = AudioFrame(self.sample_rate, 1, len(data) // 2, data)
                        phase = "consumer_backpressure"

                        # Mark before await: once emission is attempted, never replay this request.
                        emitted += 1
                        if emitted == 1:
                            logger.debug(
                                "TTS FIRST PCM provider=%s request_id=%s "
                                "attempt=%d elapsed_ms=%.1f attempt_elapsed_ms=%.1f",
                                self._provider,
                                request_id,
                                attempt,
                                (clock() - started) * 1000,
                                (clock() - attempt_started) * 1000,
                            )
                        before = clock()
                        try:
                            await emit(frame)
                        finally:
                            blocked += clock() - before
                    if last:
                        break

                if not total:
                    raise RuntimeError(f"{self._provider} TTS returned no audio")

                logger.debug(
                    "TTS COMPLETE provider=%s request_id=%s attempt=%d pcm_seconds=%.3f "
                    "http_wait_seconds=%.3f retry_wait_seconds=%.3f consumer_wait_seconds=%.3f",
                    self._provider,
                    request_id,
                    attempt,
                    total / (2 * self.sample_rate),
                    http_wait,
                    retry_wait,
                    blocked,
                )
                return
            except asyncio.CancelledError:
                logger.debug(
                    "TTS CANCELLED provider=%s request_id=%s attempt=%d phase=%s frames=%d",
                    self._provider,
                    request_id,
                    attempt,
                    phase,
                    emitted,
                )
                raise
            except Exception as error:
                status = error.status if isinstance(error, TTSHTTPError) else None
                network_failure = phase in ("response_headers", "first_audio", "audio_read")
                transient = (
                    network_failure
                    and isinstance(error, (TimeoutError | aiohttp.ClientError))
                    and not isinstance(error, (aiohttp.ClientSSLError | aiohttp.InvalidURL))
                ) or status in (408, 429, 500, 502, 503, 504)
                delay = settings.retry_interval * attempt
                if isinstance(error, TTSHTTPError) and error.retry_after is not None:
                    delay = max(delay, error.retry_after)
                retry = (
                    transient
                    and not emitted
                    and attempt <= settings.max_retries
                    and remaining > delay
                )
                logger.warning(
                    "TTS REQUEST FAILED provider=%s request_id=%s attempt=%d phase=%s "
                    "error_type=%s status=%s frames=%d received_bytes=%d retry=%s "
                    "attempt_elapsed_ms=%.1f retry_delay_ms=%.1f",
                    self._provider,
                    request_id,
                    attempt,
                    phase,
                    type(error).__name__,
                    status,
                    emitted,
                    received,
                    retry,
                    (clock() - attempt_started) * 1000,
                    delay * 1000 if retry else 0.0,
                )
                if not retry:
                    if isinstance(error, aiohttp.ClientError):
                        raise TTSTransportError(
                            self._provider, phase, type(error).__name__
                        ) from None
                    raise
            finally:
                if response is not None:
                    # Incomplete bodies must not return a dirty connection to the shared pool.
                    response.close()

            before = clock()
            try:
                await asyncio.sleep(delay)
            finally:
                waited = clock() - before
                retry_wait += waited
                remaining = max(0.0, remaining - waited)

    async def _close(self) -> None:
        results = await asyncio.gather(
            *(stream.aclose() for stream in tuple(self._streams)), return_exceptions=True
        )
        errors = [value for value in results if isinstance(value, BaseException)]
        if self._client is not None:
            try:
                await self._client.close()
            except BaseException as error:
                errors.append(error)
        self._streams.clear()
        for index, error in enumerate(errors):
            if isinstance(error, asyncio.CancelledError):
                failure = RuntimeError("TTS cleanup operation cancelled itself")
                failure.__cause__ = error
                errors[index] = failure
        if errors:
            raise BaseExceptionGroup("TTS provider cleanup failed", errors)

    async def aclose(self) -> None:
        self._check_loop()
        if self._close_task is None:
            name = f"tts_close:{self._provider}"
            self._close_task = asyncio.create_task(self._close(), name=name)
            self._close_task.add_done_callback(self._observe)
        await wait_for_cleanup(self._close_task)


class _PCMStream(TTSStreamBase):
    def __init__(self, provider: PCMHTTPProvider, payload: dict[str, str]) -> None:
        self._provider, self._payload = provider, payload
        self.request_id = uuid4().hex

        self._frames: deque[AudioFrame] = deque()
        self._changed, self._space = asyncio.Event(), asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._error: BaseException | None = None
        self._cancel_requested = False
        self._error_observed = self._done = self._exhausted = self._reading = False

    async def _emit(self, frame: AudioFrame) -> None:
        while len(self._frames) >= self._provider._settings.queue_frames:
            self._space.clear()
            await self._space.wait()

        self._frames.append(frame)
        self._changed.set()

    def _completed(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            if not self._cancel_requested:
                self._error = RuntimeError("TTS producer cancelled without stream closure")
        else:
            self._error = task.exception()

        self._done = True
        self._changed.set()

    async def __anext__(self) -> AudioFrame:
        if self._reading:
            raise RuntimeError("A TTS stream permits only one concurrent reader")
        if self._exhausted:
            raise StopAsyncIteration
        if self._close_task is not None or self._provider._close_task is not None:
            raise RuntimeError("TTS stream closed before complete consumption")

        self._reading = True
        try:
            if self._task is None:
                self._task = asyncio.create_task(
                    self._provider._produce(self._payload, self._emit, request_id=self.request_id),
                    name="tts_pcm_request",
                )
                self._task.add_done_callback(self._completed)

            while True:
                # Recheck after every wakeup, even when audio and closure arrive together.
                if self._close_task is not None or self._provider._close_task is not None:
                    raise RuntimeError("TTS stream closed before complete consumption")
                if self._frames:
                    frame = self._frames.popleft()
                    self._space.set()
                    return frame

                if self._done:
                    error = self._error
                    self._error_observed = True
                    self._exhausted = error is None
                    await self.aclose()
                    if error is not None:
                        raise error
                    raise StopAsyncIteration
                self._changed.clear()
                await self._changed.wait()

        except asyncio.CancelledError as original:
            try:
                await self.aclose()
            except BaseException as cleanup:
                raise original from cleanup
            raise
        finally:
            self._reading = False

    async def _close(self) -> None:
        task = self._task
        try:
            if task is not None:
                if not task.done() and not task.cancelling():
                    self._cancel_requested = True
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                self._completed(task)
            if self._error is not None and not self._error_observed:
                self._error_observed = True
                raise self._error
        finally:
            self._frames.clear()
            self._payload.clear()
            self._provider._streams.discard(self)
            self._changed.set()
            self._space.set()

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="tts_stream_close")
            self._close_task.add_done_callback(self._provider._observe)
            self._changed.set()
        await wait_for_cleanup(self._close_task)
