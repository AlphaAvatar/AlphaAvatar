# Copyright 2025 AlphaAvatar project
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
from collections.abc import AsyncGenerator, AsyncIterable
from typing import TYPE_CHECKING

from livekit import rtc
from livekit.agents import ModelSettings, stt, utils, vad
from livekit.agents.types import (
    DEFAULT_API_CONNECT_OPTIONS,
    NOT_GIVEN,
    APIConnectOptions,
    NotGivenOr,
)

from alphaavatar.agents.log import logger

if TYPE_CHECKING:
    from alphaavatar.agents.avatar import AvatarEngine

    from .base import PersonaBase


DEFAULT_STREAM_ADAPTER_API_CONNECT_OPTIONS = APIConnectOptions(
    max_retry=0, timeout=DEFAULT_API_CONNECT_OPTIONS.timeout
)


async def speaker_node(
    engine: AvatarEngine,
    audio: AsyncIterable[rtc.AudioFrame],
    model_settings: ModelSettings,
) -> AsyncGenerator[stt.SpeechEvent, None]:
    """Override implementation for `Agent.default.stt_node`"""
    activity = engine._get_activity_or_raise()
    assert activity.stt is not None, "stt_node called but no STT node is available"

    if not activity.vad:
        raise RuntimeError(
            "AlphaAvatar Persona Plugin require a VAD plugin, please add a VAD to the AgentTask/VoiceAgent to enable Persona Plugin."
        )

    wrapped_speaker = SpeakerAdapter(stt=activity.stt, vad=activity.vad, persona=engine.persona)

    conn_options = activity.session.conn_options.stt_conn_options
    async with wrapped_speaker.stream(conn_options=conn_options) as stream:

        @utils.log_exceptions(logger=logger)
        async def _forward_input() -> None:
            async for frame in audio:
                stream.push_frame(frame)

        forward_task = asyncio.create_task(_forward_input())
        try:
            async for event in stream:
                yield event
        finally:
            await utils.aio.cancel_and_wait(forward_task)


class SpeakerAdapter(stt.StreamAdapter):
    def __init__(self, *, stt: stt.STT, vad: vad.VAD, persona: PersonaBase) -> None:
        super().__init__(stt=stt, vad=vad)
        self._activity_persona = persona

    def stream(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> SpeakerStreamBase:
        return self._activity_persona.speaker_stream(
            self,
            vad=self._vad,
            wrapped_stt=self._stt,
            language=language,
            conn_options=conn_options,
            activity_persona=self._activity_persona,
        )


class SpeakerStreamBase(stt.RecognizeStream):
    """Called every time voice input is activated"""

    def __init__(
        self,
        stt: stt.STT,
        *,
        vad: vad.VAD,
        wrapped_stt: stt.STT,
        language: NotGivenOr[str],
        conn_options: APIConnectOptions,
        activity_persona: PersonaBase,
    ) -> None:
        super().__init__(stt=stt, conn_options=DEFAULT_STREAM_ADAPTER_API_CONNECT_OPTIONS)
        self._vad = vad
        self._wrapped_stt = wrapped_stt
        self._wrapped_stt_conn_options = conn_options
        self._language = language
        self._activity_persona = activity_persona

    @abstractmethod
    async def _run(self) -> None: ...
