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
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from functools import partial
from math import isfinite
from typing import Protocol
from urllib.parse import urlsplit
from uuid import uuid4

import aiohttp

from alphaavatar.agents.avatar.voice import TTSBase, TTSStreamBase
from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.media import AudioFrame

logger = logging.getLogger(__name__)

type PCMPayload = dict[str, str | float]


@dataclass(frozen=True, slots=True, kw_only=True)
class PCMSettings:
    # Logical HTTP/retry waiting budget; overlapping attempts count once, not local playout.
    timeout: float = 30.0
    first_audio_timeout: float = 5.0
    read_timeout: float = 15.0
    # Observation only: a warning never restarts or cancels an attempt.
    slow_response_after: float = 2.5
    trust_env: bool = False
    # One speculative first-audio attempt by default; None disables it. It can be billed.
    first_audio_hedge_after: float | None = 2.5
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
        if type(self.trust_env) is not bool:
            raise ValueError("trust_env must be bool")
        if type(self.max_retries) is not int or not 0 <= self.max_retries <= 3:
            raise ValueError("max_retries must be an integer in 0..3")
        for name in (
            "timeout",
            "first_audio_timeout",
            "read_timeout",
            "slow_response_after",
            "retry_interval",
            "max_audio_seconds",
        ):
            value = getattr(self, name)
            if type(value) not in (int, float) or not isfinite(value) or not 0 < value <= 3600:
                raise ValueError(f"{name} must be finite and in (0, 3600]")

        if self.first_audio_hedge_after is not None:
            delay = self.first_audio_hedge_after
            if (
                type(delay) not in (int, float)
                or not isfinite(delay)
                or not 0 < delay < min(self.first_audio_timeout, self.timeout)
                or self.max_retries < 1
            ):
                raise ValueError("First-audio hedging requires retry quota and a shorter deadline")


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
    def __init__(
        self, provider: str, phase: str, error_type: str, *, retryable: bool = False
    ) -> None:
        self.provider, self.phase, self.error_type = provider, phase, error_type
        self.retryable = retryable
        super().__init__(f"{provider} TTS transport failed during {phase}: {error_type}")


class PCMResponse(Protocol):
    """A streaming byte response; request policy and PCM assembly stay above transport."""

    @property
    def status(self) -> int: ...

    @property
    def headers(self) -> Mapping[str, str]: ...

    async def read(self, size: int) -> bytes: ...

    async def aclose(self) -> None: ...


class _HTTPResponse:
    def __init__(self, response: aiohttp.ClientResponse) -> None:
        self._response = response
        self.status, self.headers = response.status, response.headers

    async def read(self, size: int) -> bytes:
        return await self._response.content.read(size)

    async def aclose(self) -> None:
        self._response.close()


class _RequestBudget:
    def __init__(self, settings: PCMSettings) -> None:
        self.clock = asyncio.get_running_loop().time
        self.started = self._updated = self.clock()
        self._remaining, self._waiting = settings.timeout, 0
        self.attempts, self.limit = 0, settings.max_retries + 1
        self.hedge_allowed = True
        self.emitted = False
        self.retry_not_before = 0.0

    def available(self) -> float:
        now = self.clock()
        if self._waiting:
            self._remaining = max(0.0, self._remaining - (now - self._updated))
        self._updated = now
        return self._remaining

    def enter(self) -> None:
        self.available()
        self._waiting += 1

    def leave(self) -> None:
        self.available()
        self._waiting -= 1

    def claim(self) -> int | None:
        if self.attempts >= self.limit or self.emitted:
            return None
        self.attempts += 1
        return self.attempts


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

        self._hedge_busy = False
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

    @property
    def max_concurrent_streams(self) -> int:
        return self._settings.max_streams

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
    def _payload(self, text: str) -> PCMPayload: ...

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
            # Resident streams plus one optional hedge bound connection ownership.
            self._client = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(
                    limit=self._settings.max_streams
                    + int(self._settings.first_audio_hedge_after is not None)
                ),
                # Explicit read deadlines below pause while the bounded PCM queue is full.
                timeout=aiohttp.ClientTimeout(
                    total=None, sock_connect=self._settings.first_audio_timeout, sock_read=None
                ),
                auto_decompress=False,
                trust_env=self._settings.trust_env,
                read_bufsize=max(4096, self._frame_bytes * self._settings.queue_frames),
            )
        return self._client

    async def _open_response(self, payload: PCMPayload) -> PCMResponse:
        response = await self._get_client().post(
            self._url,
            json=payload,
            allow_redirects=False,
            headers={"Authorization": f"Bearer {self._api_key}", "Accept-Encoding": "identity"},
        )
        return _HTTPResponse(response)

    def _transport_failure(self, error: Exception, phase: str) -> Exception:
        if isinstance(error, aiohttp.ClientError):
            return TTSTransportError(
                self._provider,
                phase,
                type(error).__name__,
                retryable=not isinstance(error, aiohttp.ClientSSLError | aiohttp.InvalidURL),
            )
        return error

    async def _close_transport(self) -> None:
        if self._client is not None:
            await self._client.close()

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
        self, payload: PCMPayload, emit: Callable[[AudioFrame], Awaitable[None]], *, request_id: str
    ) -> None:
        budget = _RequestBudget(self._settings)
        delay = self._settings.first_audio_hedge_after
        if delay is None:
            await self._produce_serial(payload, emit, request_id=request_id, budget=budget)
            return

        workers: list[asyncio.Task[None]] = []
        changed = asyncio.Event()
        winner: asyncio.Task[None] | None = None
        timer: asyncio.Task[None] | None = None
        owns_slot = False

        def settled(_: asyncio.Task) -> None:
            nonlocal owns_slot
            if owns_slot and sum(not task.done() for task in workers) < 2:
                owns_slot, self._hedge_busy = False, False
            changed.set()

        async def select(frame: AudioFrame) -> None:
            nonlocal winner
            current = asyncio.current_task()
            if winner is None:
                # Selection and cancellation contain no await: exactly one PCM source wins.
                winner = current
                budget.emitted = True
                for task in workers:
                    if task is not current and not task.done():
                        task.cancel()
                if timer is not None and not timer.done():
                    timer.cancel()
                logger.debug(
                    "TTS FIRST AUDIO SELECTED provider=%s request_id=%s "
                    "attempts=%d elapsed_ms=%.1f",
                    self._provider,
                    request_id,
                    budget.attempts,
                    (budget.clock() - budget.started) * 1000,
                )
                changed.set()
            if current is not winner:
                raise asyncio.CancelledError
            await emit(frame)

        def launch() -> None:
            task = asyncio.create_task(
                self._produce_serial(payload, select, request_id=request_id, budget=budget),
                name=f"tts_attempt:{request_id}",
            )
            workers.append(task)
            task.add_done_callback(settled)

        async def hedge() -> None:
            nonlocal owns_slot
            await asyncio.sleep(delay)
            if (
                winner is not None
                or not budget.hedge_allowed
                or budget.attempts != 1
                or budget.available() <= 0
                or self._hedge_busy
                or all(task.done() for task in workers)
            ):
                return
            # One extra connection for this provider, not one extra for every resident stream.
            owns_slot, self._hedge_busy = True, True
            logger.debug(
                "TTS HEDGE START provider=%s request_id=%s after_ms=%.1f quota=%d",
                self._provider,
                request_id,
                (budget.clock() - budget.started) * 1000,
                budget.limit,
            )
            launch()

        launch()
        timer = asyncio.create_task(hedge(), name=f"tts_first_audio_timer:{request_id}")
        timer.add_done_callback(settled)
        try:
            while True:
                changed.clear()
                if timer.done() and not timer.cancelled():
                    timer.result()
                if winner is not None:
                    await winner
                    return
                if all(task.done() for task in workers):
                    # A failed speculative attempt must not cancel a still-viable primary.
                    for task in reversed(workers):
                        if not task.cancelled() and task.exception() is not None:
                            raise task.exception()
                    raise RuntimeError("TTS attempts ended without audio")
                await changed.wait()
        finally:

            async def reap() -> None:
                nonlocal owns_slot
                tasks = (*workers, timer)
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                if owns_slot:
                    owns_slot, self._hedge_busy = False, False

            await wait_for_cleanup(asyncio.create_task(reap(), name="tts_attempt_cleanup"))

    async def _produce_serial(
        self,
        payload: PCMPayload,
        emit: Callable[[AudioFrame], Awaitable[None]],
        *,
        request_id: str,
        budget: _RequestBudget,
    ) -> None:
        settings, clock = self._settings, asyncio.get_running_loop().time
        emitted = received = 0
        blocked = http_wait = retry_wait = 0.0
        read_gaps = slow_reports = 0
        max_read_gap = 0.0
        started = budget.started

        async def network[T](
            operation: Callable[[], Awaitable[T]], phase: str, first_deadline: float
        ) -> T:
            nonlocal http_wait, read_gaps, max_read_gap
            limit = min(
                budget.available(),
                first_deadline - clock() if not emitted else settings.read_timeout,
            )
            if limit <= 0:
                raise TTSTimeoutError(self._provider, phase)
            before = clock()
            completed = False
            budget.enter()

            def report_slow() -> None:
                nonlocal slow_reports
                slow_reports += 1
                logger.warning(
                    "TTS SLOW RESPONSE provider=%s request_id=%s attempt=%d phase=%s "
                    "wait_ms=%.1f frames=%d action=continue_waiting",
                    self._provider,
                    request_id,
                    attempt,
                    phase,
                    (clock() - before) * 1000,
                    emitted,
                )

            # A slow observation does not cancel or replay a still-progressing request.
            warning = None
            if slow_reports < 3 and settings.slow_response_after < limit:
                warning = asyncio.get_running_loop().call_later(
                    settings.slow_response_after, report_slow
                )
            try:
                async with asyncio.timeout(limit):
                    value = await operation()
                    completed = True
                    return value
            except TimeoutError:
                raise TTSTimeoutError(self._provider, phase) from None
            finally:
                if warning is not None:
                    warning.cancel()
                waited = clock() - before
                http_wait += waited
                budget.leave()
                if phase == "audio_read":
                    max_read_gap = max(max_read_gap, waited)
                    if waited >= 0.05:
                        read_gaps += 1
                        if read_gaps <= 3:
                            logger.debug(
                                "TTS PCM GAP provider=%s request_id=%s attempt=%d "
                                "read_wait_ms=%.1f pcm_seconds_before=%.3f "
                                "read_outcome=%s measurement=body_read_wait",
                                self._provider,
                                request_id,
                                attempt,
                                waited * 1000,
                                received / (2 * self.sample_rate),
                                "completed" if completed else "interrupted",
                            )

        last_error: Exception | None = None
        while True:
            attempt = budget.claim()
            if attempt is None:
                if last_error is not None:
                    raise last_error
                raise RuntimeError("TTS attempt quota exhausted")
            phase, response = "response_headers", None
            attempt_started = clock()
            first_deadline = attempt_started + min(budget.available(), settings.first_audio_timeout)
            logger.debug(
                "TTS REQUEST provider=%s request_id=%s attempt=%d first_audio_timeout_ms=%.1f",
                self._provider,
                request_id,
                attempt,
                (first_deadline - attempt_started) * 1000,
            )
            try:
                response = await network(
                    partial(self._open_response, payload), phase, first_deadline
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
                pending = bytearray()
                while True:
                    phase = "first_audio" if not emitted else "audio_read"
                    # A network fragment is not an audio frame. Reset the idle deadline
                    # on byte progress; retain the first-audio and aggregate hard limits.
                    data = await network(
                        partial(response.read, self._frame_bytes - len(pending)),
                        phase,
                        first_deadline,
                    )
                    last = not data
                    if data:
                        pending.extend(data)
                        received += len(data)
                        if total + len(pending) > self._max_audio_bytes:
                            raise RuntimeError("TTS audio duration exceeds its limit")
                    if len(pending) < self._frame_bytes and not last:
                        continue
                    if pending:
                        phase = "pcm_validation"
                        if len(pending) % 2:
                            raise RuntimeError("TTS returned an incomplete PCM sample")
                        if total == 0 and (
                            (pending.startswith(b"RIFF") and pending[8:12] == b"WAVE")
                            or pending.startswith((b"ID3", b"OggS", b"fLaC"))
                        ):
                            raise RuntimeError("TTS returned an audio container instead of PCM")
                        frame = AudioFrame(self.sample_rate, 1, len(pending) // 2, bytes(pending))
                        total += len(pending)
                        pending.clear()
                        phase = "consumer_backpressure"

                        # An attempted emission forbids transparent retries, even if the
                        # downstream consumer is cancelled before returning a receipt.
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
                    "http_wait_seconds=%.3f retry_wait_seconds=%.3f consumer_wait_seconds=%.3f "
                    "body_read_gaps=%d max_body_read_gap_ms=%.1f",
                    self._provider,
                    request_id,
                    attempt,
                    total / (2 * self.sample_rate),
                    http_wait,
                    retry_wait,
                    blocked,
                    read_gaps,
                    max_read_gap * 1000,
                )
                return
            except asyncio.CancelledError:
                logger.debug(
                    "TTS CANCELLED provider=%s request_id=%s attempt=%d phase=%s frames=%d "
                    "body_read_gaps=%d max_body_read_gap_ms=%.1f",
                    self._provider,
                    request_id,
                    attempt,
                    phase,
                    emitted,
                    read_gaps,
                    max_read_gap * 1000,
                )
                raise
            except Exception as error:
                budget.hedge_allowed = False
                last_error = self._transport_failure(error, phase)
                status = response.status if response is not None else None
                if isinstance(last_error, TTSHTTPError):
                    status = last_error.status
                network_failure = phase in ("response_headers", "first_audio", "audio_read")
                transient = (
                    network_failure
                    and (
                        isinstance(last_error, TimeoutError)
                        or isinstance(last_error, TTSTransportError)
                        and last_error.retryable
                    )
                ) or status in (408, 429, 500, 502, 503, 504)
                delay = settings.retry_interval * attempt
                if isinstance(last_error, TTSHTTPError) and last_error.retry_after is not None:
                    delay = max(delay, last_error.retry_after)
                    budget.retry_not_before = max(budget.retry_not_before, clock() + delay)
                delay = max(delay, budget.retry_not_before - clock())
                retry = (
                    transient
                    and not emitted
                    and not budget.emitted
                    and budget.attempts < budget.limit
                    and budget.available() > delay
                )
                logger.warning(
                    "TTS REQUEST FAILED provider=%s request_id=%s attempt=%d phase=%s "
                    "error_type=%s status=%s frames=%d received_bytes=%d retry=%s "
                    "attempt_elapsed_ms=%.1f retry_delay_ms=%.1f "
                    "body_read_gaps=%d max_body_read_gap_ms=%.1f",
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
                    read_gaps,
                    max_read_gap * 1000,
                )
                if not retry:
                    if last_error is not error:
                        raise last_error from None
                    raise
            finally:
                if response is not None:
                    # The transport owns its context manager even after cancellation or hedging.
                    await wait_for_cleanup(
                        asyncio.create_task(response.aclose(), name="tts_response_close")
                    )

            before = clock()
            budget.enter()
            try:
                while delay > 0:
                    if delay >= budget.available():
                        raise last_error
                    await asyncio.sleep(delay)
                    delay = max(0.0, budget.retry_not_before - clock())
            finally:
                waited = clock() - before
                retry_wait += waited
                budget.leave()

    async def _close(self) -> None:
        results = await asyncio.gather(
            *(stream.aclose() for stream in tuple(self._streams)), return_exceptions=True
        )
        errors = [value for value in results if isinstance(value, BaseException)]
        try:
            await self._close_transport()
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
    def __init__(self, provider: PCMHTTPProvider, payload: PCMPayload) -> None:
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
