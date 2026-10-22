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


class VoiceAITTS(PCMHTTPProvider):
    def __init__(
        self,
        *,
        model: str,
        speaker: str | None = None,
        language: str = "en",
        api_key: str | None = None,
        base_url: str | None = None,
        settings: PCMSettings | None = None,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("Voice.ai TTS requires a model")
        if speaker is not None and (not isinstance(speaker, str) or not speaker.strip()):
            raise ValueError("Voice.ai speaker must be nonempty when supplied")
        if not isinstance(language, str) or not language.strip():
            raise ValueError("Voice.ai TTS requires a language")

        self._model, self._speaker, self._language = model, speaker, language
        base = base_url if base_url is not None else "https://dev.voice.ai"
        super().__init__(
            provider="voiceai",
            url=f"{base.rstrip('/')}/api/v1/tts/speech/stream",
            api_key=api_key if api_key is not None else os.getenv("VOICEAI_API_KEY", ""),
            sample_rate=32000,
            settings=settings or PCMSettings(),
        )

    def _payload(self, text: str) -> dict[str, str]:
        payload = {
            "model": self._model,
            "text": text,
            "language": self._language,
            "audio_format": "pcm_32000",
        }
        if self._speaker is not None:
            payload["voice_id"] = self._speaker
        return payload
