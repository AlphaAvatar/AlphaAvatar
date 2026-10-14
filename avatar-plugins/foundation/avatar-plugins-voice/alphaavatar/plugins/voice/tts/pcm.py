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
from abc import abstractmethod
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from math import isfinite
from urllib.parse import urlsplit

import aiohttp

from alphaavatar.agents.avatar.voice import TTSBase, TTSStreamBase
from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.media import AudioFrame


@dataclass(frozen=True, slots=True)
class PCMSettings:
    timeout: float = 30.0
    frame_size_ms: int = 20
    queue_frames: int = 8
    max_streams: int = 4
    max_audio_seconds: float = 120.0

    def __post_init__(self) -> None:
        for name, maximum in (("frame_size_ms", 100), ("queue_frames", 128), ("max_streams", 32)):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f"{name} must be an integer in 1..{maximum}")
        for name in ("timeout", "max_audio_seconds"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not isfinite(value) or not 0 < value <= 3600:
                raise ValueError(f"{name} must be finite and in (0, 3600]")


class TTSHTTPError(RuntimeError):
    """Remote status without credentials, input text, URLs or response bodies."""

    def __init__(self, provider: str, status: int) -> None:
        self.provider, self.status = provider, status
        super().__init__(f"{provider} TTS request failed with HTTP {status}")


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
                timeout=aiohttp.ClientTimeout(total=None, sock_connect=10.0),
                auto_decompress=False,
                read_bufsize=max(4096, self._frame_bytes * self._settings.queue_frames),
            )
        return self._client

    async def _produce(
        self, payload: dict[str, str], emit: Callable[[AudioFrame], Awaitable[None]]
    ) -> None:
        # The absolute deadline includes HTTP and bounded local backpressure. No auto replay.
        async with asyncio.timeout(self._settings.timeout):
            try:
                async with self._get_client().post(
                    self._url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Accept-Encoding": "identity",
                    },
                    allow_redirects=False,
                ) as response:
                    if response.status != 200:
                        raise TTSHTTPError(self._provider, response.status)

                    content_type = response.headers.get("Content-Type", "")
                    content_type = content_type.split(";", 1)[0].strip().lower()
                    if content_type not in ("audio/pcm", "audio/x-pcm", "application/octet-stream"):
                        raise RuntimeError(f"{self._provider} TTS did not return raw PCM")
                    if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                        raise RuntimeError(f"{self._provider} TTS returned encoded PCM")

                    total = 0
                    while True:
                        last = False
                        try:
                            data = await response.content.readexactly(self._frame_bytes)
                        except asyncio.IncompleteReadError as error:
                            data, last = error.partial, True
                        if data:
                            if len(data) % 2:
                                raise RuntimeError("TTS returned an incomplete PCM sample")
                            if total == 0 and (
                                (data.startswith(b"RIFF") and data[8:12] == b"WAVE")
                                or data.startswith((b"ID3", b"OggS", b"fLaC"))
                            ):
                                raise RuntimeError("TTS returned an audio container instead of PCM")
                            total += len(data)
                            if total > self._max_audio_bytes:
                                raise RuntimeError("TTS audio duration exceeds its limit")
                            await emit(AudioFrame(self.sample_rate, 1, len(data) // 2, data))
                        if last:
                            break
                    if not total:
                        raise RuntimeError(f"{self._provider} TTS returned no audio")
            except aiohttp.ClientError:
                # SDK exception reprs can contain request details; expose a safe transport failure.
                raise RuntimeError(f"{self._provider} TTS transport failed") from None

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
                    self._provider._produce(self._payload, self._emit), name="tts_pcm_request"
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
