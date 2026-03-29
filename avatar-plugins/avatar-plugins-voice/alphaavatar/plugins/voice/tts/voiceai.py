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
import os
from dataclasses import dataclass, replace
from typing import Literal

import httpx
from livekit.agents import (
    APIConnectionError,
    APIConnectOptions,
    APIStatusError,
    APITimeoutError,
    tts,
)
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, NOT_GIVEN, NotGivenOr
from livekit.agents.utils import aio, is_given

# Voice.ai docs list pcm_32000 as a supported PCM output format.
# Using pcm_32000 keeps sample_rate aligned with LiveKit emitter metadata.
SAMPLE_RATE = 32000
NUM_CHANNELS = 1

DEFAULT_MODEL = "voiceai-tts-v1-latest"
DEFAULT_VOICE_ID = "d1bf0f33-8e0e-4fbf-acf8-45c3c6262513"  # DEFAULE VOICE NAME: "Ellie" developed by voice.ai, you can also use your custom voice_id if you have one. See https://docs.voice.ai/docs/tts-api-reference/create-tts for more details.
DEFAULT_LANGUAGE = "en"
DEFAULT_BASE_URL = "https://dev.voice.ai"

# Keep this open-ended because Voice.ai supports variants like:
# mp3, wav, pcm, mp3_44100_128, opus_48000_64, pcm_32000, wav_24000, etc.
RESPONSE_FORMATS = (
    Literal[
        "mp3",
        "wav",
        "pcm",
        "pcm_32000",
        "pcm_24000",
        "wav_24000",
        "wav_32000",
    ]
    | str
)


@dataclass
class _TTSOptions:
    model: str
    voice_id: str | None
    language: str
    response_format: RESPONSE_FORMATS


class TTS(tts.TTS):
    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        voice_id: str | None = DEFAULT_VOICE_ID,
        language: str = DEFAULT_LANGUAGE,
        api_key: NotGivenOr[str] = NOT_GIVEN,
        base_url: str = DEFAULT_BASE_URL,
        response_format: NotGivenOr[RESPONSE_FORMATS] = NOT_GIVEN,
        timeout: float = 30.0,
        **kwargs,
    ) -> None:
        """
        Voice.ai TTS using the official HTTP chunked streaming endpoint.

        Docs:
          POST {base_url}/api/v1/tts/speech/stream
          Authorization: Bearer <VOICEAI_API_KEY>
        """
        fmt = response_format if is_given(response_format) else "mp3"

        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=SAMPLE_RATE,
            num_channels=NUM_CHANNELS,
        )

        api_key_value = api_key if is_given(api_key) else os.getenv("VOICEAI_API_KEY")
        if not api_key_value:
            raise ValueError(
                "VoiceAI API key is required, either pass api_key=... or set VOICEAI_API_KEY"
            )

        self._opts = _TTSOptions(
            model=model,
            voice_id=voice_id,
            language=language,
            response_format=fmt,
        )
        self._api_key = api_key_value
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=15.0, read=timeout, write=15.0, pool=5.0),
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=50,
                max_keepalive_connections=50,
                keepalive_expiry=120,
            ),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )

        self._prewarm_task: asyncio.Task | None = None

    @property
    def model(self) -> str:
        return self._opts.model

    @property
    def provider(self) -> str:
        return "voice.ai"

    def update_options(
        self,
        *,
        model: NotGivenOr[str] = NOT_GIVEN,
        voice_id: NotGivenOr[str | None] = NOT_GIVEN,
        language: NotGivenOr[str] = NOT_GIVEN,
        response_format: NotGivenOr[RESPONSE_FORMATS] = NOT_GIVEN,
    ) -> None:
        if is_given(model):
            self._opts.model = model
        if is_given(voice_id):
            self._opts.voice_id = voice_id
        if is_given(language):
            self._opts.language = language
        if is_given(response_format):
            self._opts.response_format = response_format

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> ChunkedStream:
        return ChunkedStream(tts=self, input_text=text, conn_options=conn_options)

    def prewarm(self) -> None:
        async def _prewarm() -> None:
            # Lightweight prewarm; don't fail hard.
            try:
                await self._client.get(f"{self._base_url}/")
            except Exception:
                pass

        self._prewarm_task = asyncio.create_task(_prewarm())

    async def aclose(self) -> None:
        if self._prewarm_task:
            await aio.cancel_and_wait(self._prewarm_task)
        await self._client.aclose()


class ChunkedStream(tts.ChunkedStream):
    def __init__(
        self,
        *,
        tts: TTS,
        input_text: str,
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._tts: TTS = tts
        self._opts = replace(tts._opts)

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        url = f"{self._tts._base_url}/api/v1/tts/speech/stream"

        payload: dict[str, object] = {
            "text": self.input_text,
            "model": self._opts.model,
            "language": self._opts.language,
            "audio_format": self._opts.response_format,
        }
        if self._opts.voice_id:
            payload["voice_id"] = self._opts.voice_id

        # Map requested output format to a mime type that matches what we push.
        fmt = str(self._opts.response_format)
        if fmt.startswith("pcm"):
            mime_type = "audio/pcm"
        elif fmt.startswith("wav"):
            mime_type = "audio/wav"
        elif fmt.startswith("opus"):
            mime_type = "audio/opus"
        else:
            mime_type = "audio/mp3"

        try:
            async with self._tts._client.stream(
                "POST",
                url,
                json=payload,
                timeout=httpx.Timeout(
                    connect=self._conn_options.timeout,
                    read=self._tts._timeout,
                    write=15.0,
                    pool=5.0,
                ),
            ) as resp:
                try:
                    resp.raise_for_status()
                except httpx.HTTPStatusError as e:
                    body = await resp.aread()
                    raise APIStatusError(
                        message=body.decode("utf-8", errors="replace") or str(e),
                        status_code=resp.status_code,
                        request_id=resp.headers.get("x-request-id"),
                        body=body.decode("utf-8", errors="replace"),
                    ) from None

                output_emitter.initialize(
                    request_id=resp.headers.get("x-request-id", ""),
                    sample_rate=SAMPLE_RATE,
                    num_channels=NUM_CHANNELS,
                    mime_type=mime_type,
                )

                async for chunk in resp.aiter_bytes():
                    if chunk:
                        output_emitter.push(chunk)

                output_emitter.flush()

        except httpx.ReadTimeout:
            raise APITimeoutError() from None
        except httpx.ConnectTimeout:
            raise APITimeoutError() from None
        except APIStatusError:
            raise
        except httpx.HTTPError as e:
            raise APIConnectionError() from e
        except Exception as e:
            raise APIConnectionError() from e
