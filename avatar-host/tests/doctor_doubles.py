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
"""Controlled stand-ins for Doctor's diagnostic session: no model file and no network.

Only the external services and the model files are replaced. Router, Context, Loop, Engine,
output runtime and the shared inference runtime around them are production code. Runners
are spawned by name, so they live here, on pytest's pythonpath.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import numpy as np

from alphaavatar.agents.avatar.provider.base import StreamingLLMBase
from alphaavatar.agents.avatar.provider.enums import ModelFinishReason, ModelRole
from alphaavatar.agents.avatar.provider.errors import ModelCapabilityError
from alphaavatar.agents.avatar.provider.schemas import (
    ModelImagePart,
    ModelInputMessage,
    ModelTextPart,
)
from alphaavatar.agents.avatar.provider.schemas.stream import (
    ModelItemCompleted,
    ModelResponseCompleted,
    ModelTextDelta,
)
from alphaavatar.agents.avatar.voice import (
    STTBase,
    STTCapabilities,
    STTInputMode,
    STTStreamBase,
    TranscriptionEvent,
    TranscriptionEventType,
    TTSBase,
    TTSStreamBase,
)
from alphaavatar.agents.memory.base import MemoryBase
from alphaavatar.agents.persona.base import PersonaBase
from alphaavatar.agents.runtime.capability.registry import AvatarCapabilityRegistry
from alphaavatar.agents.runtime.inference.runner import InferenceRunner
from alphaavatar.core.media import AudioFrame

TTS_RATE = 24_000
TTS_FRAME = TTS_RATE // 50  # 20 ms


class SpeechRunner(InferenceRunner):
    """Silero's request and response layout: a loud window is speech, the state passes on."""

    INFERENCE_METHOD = "alphaavatar.voice.vad.silero"
    REPLICABLE = True

    def run(self, data: bytes) -> bytes | None:
        values = np.frombuffer(data, dtype=np.float32)
        if values.size != 512 + 64 + 256:
            raise ValueError("Invalid Silero request size")
        response = np.empty(257, dtype=np.float32)
        response[0] = float(np.abs(values[:512]).mean() > 0.02)
        response[1:] = values[576:]
        return response.tobytes()


class EndpointRunner(InferenceRunner):
    """Smart Turn's layout: every assessed window ends its turn. It starts only offline."""

    INFERENCE_METHOD = "alphaavatar.router.turn_taking.smart_turn_v3"
    REPLICABLE = True

    def initialize(self) -> None:
        from alphaavatar.agents.utils.files.model.model_files import models_offline

        if not models_offline():
            raise RuntimeError("Model downloads are allowed in this runner process")

    def run(self, data: bytes) -> bytes | None:
        return np.asarray([1.0], dtype=np.float32).tobytes()


class StuckRunner(InferenceRunner):
    """A runner whose start never finishes on its own: a model load that hangs."""

    INFERENCE_METHOD = "test.doctor.stuck"

    def initialize(self) -> None:
        import time

        time.sleep(60)


class ScriptedLLM(StreamingLLMBase):
    """Answers from what the request carries: a picture means it can see the card."""

    def __init__(self, *, images: bool = True) -> None:
        self.images = images  # False: refuse images, as a model without vision input does.
        self.requests: list[object] = []

    def validate_input(self, *, require_input_adapter: bool = False) -> None:
        pass

    async def ainvoke_structured(self, model_input, *, output_schema, include_raw=False):
        raise NotImplementedError

    async def aclose(self) -> None:
        pass

    @staticmethod
    def parts(request) -> list[object]:
        return [
            part
            for item in request.input.items
            if isinstance(item, ModelInputMessage)
            for part in item.parts
        ]

    @asynccontextmanager
    async def stream(self, request) -> AsyncIterator[AsyncIterator[object]]:
        self.requests.append(request)
        parts = self.parts(request)
        text = " ".join(part.text for part in parts if isinstance(part, ModelTextPart)).lower()
        images = any(isinstance(part, ModelImagePart) for part in parts)
        if images and not self.images:
            raise ModelCapabilityError("This model accepts no image input")
        if "plus" in text:
            answer = "Two plus three is five."
        elif images:
            answer = "The card is green."
        else:
            answer = "I cannot tell."

        async def events() -> AsyncIterator[object]:
            response = f"response:{request.request_id}"
            message = ModelInputMessage(
                id=f"answer:{request.request_id}",
                role=ModelRole.ASSISTANT,
                parts=(ModelTextPart(answer),),
            )
            await asyncio.sleep(0.05)
            words = answer.split(" ")
            for index, word in enumerate(words):
                yield ModelTextDelta(
                    request_id=request.request_id,
                    response_id=response,
                    item_id=message.id,
                    output_index=0,
                    content_index=0,
                    text=word if not index else f" {word}",
                )
            yield ModelItemCompleted(
                request_id=request.request_id, response_id=response, output_index=0, item=message
            )
            yield ModelResponseCompleted(
                request_id=request.request_id,
                response_id=response,
                items=(message,),
                finish_reason=ModelFinishReason.STOP,
            )

        yield events()


class ScriptedSTTStream(STTStreamBase):
    def __init__(self, stt: ScriptedSTT, source_id: str) -> None:
        self._stt, self.source_id = stt, source_id
        self._events: asyncio.Queue[TranscriptionEvent | None] = asyncio.Queue()

    def push_frame(self, frame: AudioFrame, *, segment_id: str) -> bool:
        return True

    def commit_segment(self, segment_id: str) -> bool:
        text = self._stt.transcripts.pop(0) if self._stt.transcripts else ""
        loop = asyncio.get_running_loop()
        loop.call_later(
            0.05,
            self._events.put_nowait,
            TranscriptionEvent(
                TranscriptionEventType.FINAL_TRANSCRIPT, self.source_id, segment_id, text
            ),
        )
        return True

    def flush(self) -> bool:
        return True

    def end_input(self) -> bool:
        self._events.put_nowait(None)
        return True

    async def _iterate(self) -> AsyncIterator[TranscriptionEvent]:
        while (event := await self._events.get()) is not None:
            yield event

    def __aiter__(self) -> AsyncIterator[TranscriptionEvent]:
        return self._iterate()

    async def aclose(self) -> None:
        self._events.put_nowait(None)


class ScriptedSTT(STTBase):
    """Segment STT: each committed segment's final is the next scripted transcript."""

    def __init__(self, transcripts: list[str]) -> None:
        self.transcripts = transcripts

    @property
    def provider(self) -> str:
        return "scripted"

    @property
    def model(self) -> str:
        return "scripted"

    @property
    def capabilities(self) -> STTCapabilities:
        return STTCapabilities(STTInputMode.SEGMENT, False, False)

    def stream(self, *, source_id: str) -> ScriptedSTTStream:
        return ScriptedSTTStream(self, source_id)


class ScriptedTTSStream(TTSStreamBase):
    def __init__(self, text: str, index: int, frames: int) -> None:
        self.request_id = f"tts-{index}"
        self._frames = max(12, len(text) // 2) if frames is None else frames

    async def __anext__(self) -> AudioFrame:
        if not self._frames:
            raise StopAsyncIteration
        self._frames -= 1
        # At real time: audio goes on well after the model's run has finished.
        await asyncio.sleep(0.02)
        return AudioFrame(TTS_RATE, 1, TTS_FRAME, b"\x10\x00" * TTS_FRAME)

    async def aclose(self) -> None:
        self._frames = 0


class ScriptedTTS(TTSBase):
    def __init__(self, *, frames: int | None = None, fail: bool = False) -> None:
        self.frames, self.fail, self.requests = frames, fail, 0

    @property
    def sample_rate(self) -> int:
        return TTS_RATE

    @property
    def num_channels(self) -> int:
        return 1

    def synthesize(self, text: str) -> ScriptedTTSStream:
        if self.fail:
            raise RuntimeError("Scripted TTS is unavailable")
        self.requests += 1
        return ScriptedTTSStream(text, self.requests, self.frames)

    async def aclose(self) -> None:
        pass


class NullMemory(MemoryBase):
    """No recall and no persistence: the session runs without Memory's services."""

    def __init__(self, **_: object) -> None:
        self._registry = AvatarCapabilityRegistry()

    @property
    def capability_registry(self) -> AvatarCapabilityRegistry:
        return self._registry

    @property
    def root_context_id(self) -> str:
        return "doctor"

    @property
    def memory_content(self) -> str:
        return ""

    def content_for(self, snapshot) -> str:
        return ""

    async def on_start(self) -> None:
        pass

    async def on_stop(self) -> None:
        pass


class NullPersona(PersonaBase):
    """No profiles and no persistence: the session runs without Persona's services."""

    def __init__(self, **_: object) -> None:
        self._registry = AvatarCapabilityRegistry()

    @property
    def capability_registry(self) -> AvatarCapabilityRegistry:
        return self._registry

    @property
    def persona_cache(self) -> dict:
        return {}

    @property
    def persona_content(self) -> str:
        return ""

    def content_for(self, snapshot) -> str:
        return ""

    def cache_for(self, participant_id: str):
        return None

    async def load_profile(self, *, participant_id: str) -> None:
        pass

    async def save(self, *, user_id: str | None = None) -> None:
        pass

    async def on_start(self) -> None:
        pass

    async def on_stop(self) -> None:
        pass
