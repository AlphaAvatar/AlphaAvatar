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
import os
import ssl
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx
import openai

from alphaavatar.core.cleanup import wait_for_cleanup

from .codec.pcm import (
    PCMHTTPProvider,
    PCMPayload,
    PCMResponse,
    PCMSettings,
    TTSHTTPError,
    TTSTransportError,
)

logger = logging.getLogger(__name__)


class _SDKResponse:
    """Adapt an SDK byte stream without asking it to collect a complete audio frame."""

    def __init__(
        self, response: Any, context: AbstractAsyncContextManager, *, max_bytes: int
    ) -> None:
        self.status, self.headers = response.status_code, response.headers
        self._context, self._max_bytes = context, max_bytes
        self._iterator = response.iter_bytes().__aiter__()
        self._pending = memoryview(b"")
        self._close_task: asyncio.Task[None] | None = None

    async def read(self, size: int) -> bytes:
        if self._close_task is not None:
            raise RuntimeError("TTS response is closed")
        while not self._pending:
            data = await anext(self._iterator, b"")
            if not data:
                return b""
            if len(data) > self._max_bytes:
                raise RuntimeError("TTS response fragment exceeds its audio limit")
            self._pending = memoryview(data)
        data = self._pending[:size].tobytes()
        self._pending = self._pending[len(data) :]
        return data

    async def aclose(self) -> None:
        if self._close_task is None:

            async def close() -> None:
                try:
                    await self._iterator.aclose()
                finally:
                    self._pending = memoryview(b"")
                    await self._context.__aexit__(None, None, None)

            self._close_task = asyncio.create_task(close(), name="tts_sdk_response_close")
        await wait_for_cleanup(self._close_task)


class OpenAITTS(PCMHTTPProvider):
    def __init__(
        self,
        *,
        model: str,
        speaker: str,
        instructions: str | None = None,
        speed: float = 1.0,
        api_key: str | None = None,
        base_url: str | None = None,
        settings: PCMSettings | None = None,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("OpenAI TTS requires a model")
        if not isinstance(speaker, str) or not speaker.strip():
            raise ValueError("OpenAI TTS requires a speaker")
        if instructions is not None and (
            not isinstance(instructions, str) or len(instructions) > 4096
        ):
            raise ValueError("TTS instructions must be a string of at most 4096 characters")
        if instructions is not None and model in ("tts-1", "tts-1-hd"):
            raise ValueError("This OpenAI TTS model does not accept instructions")

        if type(speed) not in (int, float) or not 0.25 <= speed <= 4.0:
            raise ValueError("OpenAI TTS speed must be a finite number in 0.25..4.0")

        self._model, self._speaker, self._instructions = model, speaker, instructions
        self._speed = float(speed)
        base = base_url if base_url is not None else os.getenv("OPENAI_BASE_URL")
        base = "https://api.openai.com/v1" if base is None else base
        super().__init__(
            provider="openai",
            url=f"{base.rstrip('/')}/audio/speech",
            api_key=api_key if api_key is not None else os.getenv("OPENAI_API_KEY", ""),
            sample_rate=24000,
            settings=settings or PCMSettings(),
        )
        self._base_url = base.rstrip("/")
        self._sdk: openai.AsyncOpenAI | None = None
        self._prewarm_task: asyncio.Task[None] | None = None
        logger.debug(
            "TTS CONFIG provider=openai model=%r voice=%r speed=%.3f",
            self._model,
            self._speaker,
            self._speed,
        )

    def _get_sdk(self) -> openai.AsyncOpenAI:
        self._check_loop()
        if self._close_task is not None:
            raise RuntimeError("TTS provider is closing or closed")
        if self._sdk is None:
            settings = self._settings
            limit = settings.max_streams + int(settings.first_audio_hedge_after is not None) + 1
            self._sdk = openai.AsyncOpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
                # Exactly one retry owner. SDK defaults must not multiply our attempt quota.
                max_retries=0,
                http_client=httpx.AsyncClient(
                    timeout=httpx.Timeout(
                        None,
                        connect=settings.first_audio_timeout,
                        write=settings.first_audio_timeout,
                        pool=settings.first_audio_timeout,
                    ),
                    limits=httpx.Limits(
                        max_connections=limit, max_keepalive_connections=limit, keepalive_expiry=120
                    ),
                    trust_env=settings.trust_env,
                    follow_redirects=False,
                ),
            )
        return self._sdk

    def prewarm(self) -> None:
        self._check_loop()
        if self._close_task is not None:
            raise RuntimeError("TTS provider is closing or closed")
        if self._prewarm_task is not None:
            return

        async def warm() -> None:
            started = asyncio.get_running_loop().time()
            timeout = min(2.0, self._settings.first_audio_timeout)
            status, outcome = None, "completed"
            try:
                async with asyncio.timeout(timeout):
                    # Same endpoint, proxy policy and connection pool; never a speech request.
                    await self._get_sdk().get(
                        "/", cast_to=str, options={"timeout": httpx.Timeout(timeout)}
                    )
            except asyncio.CancelledError:
                raise
            except openai.APIStatusError as error:
                # Even a 404 completed the handshake; it does not prove model availability.
                status, outcome = error.status_code, "http_response"
            except Exception as error:
                outcome = type(error).__name__
            logger.debug(
                "TTS PREWARM provider=openai outcome=%s status=%s elapsed_ms=%.1f",
                outcome,
                status,
                (asyncio.get_running_loop().time() - started) * 1000,
            )

        self._prewarm_task = asyncio.create_task(warm(), name="tts_openai_prewarm")
        self._prewarm_task.add_done_callback(self._observe)

    def _payload(self, text: str) -> PCMPayload:
        payload: PCMPayload = {
            "model": self._model,
            "voice": self._speaker,
            "speed": self._speed,
            "input": text,
            "response_format": "pcm",
            "stream_format": "audio",
        }
        if self._instructions is not None:
            payload["instructions"] = self._instructions
        return payload

    async def _open_response(self, payload: PCMPayload) -> PCMResponse:
        context = self._get_sdk().audio.speech.with_streaming_response.create(
            **payload, extra_headers={"Accept-Encoding": "identity"}
        )
        try:
            response = await context.__aenter__()
        except openai.APIStatusError as error:
            raise TTSHTTPError(
                self._provider,
                error.status_code,
                retry_after=self._retry_after(error.response.headers.get("Retry-After")),
            ) from None
        try:
            return _SDKResponse(response, context, max_bytes=self._max_audio_bytes)
        except BaseException:
            await wait_for_cleanup(
                asyncio.create_task(context.__aexit__(None, None, None), name="tts_sdk_setup_close")
            )
            raise

    def _transport_failure(self, error: Exception, phase: str) -> Exception:
        if isinstance(error, openai.APIConnectionError | httpx.RequestError):
            cause, seen, secure = error, set(), False
            # Do not retry invalid URLs or TLS verification failures hidden by SDK wrapping.
            while cause is not None and id(cause) not in seen:
                seen.add(id(cause))
                secure = secure or isinstance(cause, ssl.SSLError | httpx.UnsupportedProtocol)
                cause = cause.__cause__
            return TTSTransportError(
                self._provider, phase, type(error).__name__, retryable=not secure
            )
        return super()._transport_failure(error, phase)

    async def _close_transport(self) -> None:
        if self._prewarm_task is not None:
            if not self._prewarm_task.done():
                self._prewarm_task.cancel()
            await asyncio.gather(self._prewarm_task, return_exceptions=True)
        if self._sdk is not None:
            await self._sdk.close()
