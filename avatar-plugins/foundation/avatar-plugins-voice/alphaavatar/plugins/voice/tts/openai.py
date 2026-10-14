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

import os

from .pcm import PCMHTTPProvider, PCMSettings


class OpenAITTS(PCMHTTPProvider):
    def __init__(
        self,
        *,
        model: str,
        speaker: str,
        instructions: str | None = None,
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

        self._model, self._speaker, self._instructions = model, speaker, instructions
        base = base_url if base_url is not None else os.getenv("OPENAI_BASE_URL")
        base = "https://api.openai.com/v1" if base is None else base
        super().__init__(
            provider="openai",
            url=f"{base.rstrip('/')}/audio/speech",
            api_key=api_key if api_key is not None else os.getenv("OPENAI_API_KEY", ""),
            sample_rate=24000,
            settings=settings or PCMSettings(),
        )

    def _payload(self, text: str) -> dict[str, str]:
        payload = {
            "model": self._model,
            "voice": self._speaker,
            "input": text,
            "response_format": "pcm",
            "stream_format": "audio",
        }
        if self._instructions is not None:
            payload["instructions"] = self._instructions

        return payload
