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

from alphaavatar.agents.runtime import TurnInputModality, TurnRuntime, TurnSnapshot
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.media import TextPayload
from alphaavatar.core.time import RuntimeClock, RuntimeTimeRange
from livekit.agents import llm

from .livekit_model_input import (
    audio_content_to_observation,
    image_content_to_observation,
    message_content,
)


class LiveKitTurnInput:
    """Translate committed LiveKit user input into AlphaAvatar direct observations."""

    DIRECT_TEXT_INDICES_KEY = "alphaavatar_direct_text_indices"

    def __init__(self, *, clock: RuntimeClock, turn_runtime: TurnRuntime) -> None:
        self._clock = clock
        self._turn_runtime = turn_runtime

    @staticmethod
    def latest_user_message(chat_ctx: llm.ChatContext) -> llm.ChatMessage | None:
        return next(
            (
                item
                for item in reversed(chat_ctx.items)
                if isinstance(item, llm.ChatMessage) and item.role == "user"
            ),
            None,
        )

    @classmethod
    def _direct_text_indices(cls, message: llm.ChatMessage, *, transcribed: bool) -> set[int]:
        configured = (message.extra or {}).get(cls.DIRECT_TEXT_INDICES_KEY)
        if isinstance(configured, list):
            return {index for index in configured if isinstance(index, int) and index >= 0}
        if transcribed or message.transcript_confidence is not None:
            return set()
        return {
            index
            for index, item in enumerate(message_content(message))
            if isinstance(item, str) and item.strip()
        }

    @classmethod
    def _modality(
        cls,
        message: llm.ChatMessage,
        *,
        direct_text_indices: set[int],
        transcribed: bool,
    ) -> TurnInputModality:
        content = message_content(message)
        has_image = any(isinstance(item, llm.ImageContent) for item in content)
        has_audio = (
            transcribed
            or message.transcript_confidence is not None
            or any(isinstance(item, llm.AudioContent) for item in content)
        )
        has_direct_text = bool(direct_text_indices)
        if sum((has_image, has_audio, has_direct_text)) > 1:
            return TurnInputModality.MULTIMODAL
        if has_image:
            return TurnInputModality.IMAGE
        if has_audio:
            return TurnInputModality.AUDIO
        return TurnInputModality.TEXT

    def commit_message(
        self,
        message: llm.ChatMessage,
        *,
        source: str,
        transcribed: bool = False,
    ) -> TurnSnapshot:
        if existing := self._turn_runtime.get(message.id):
            return existing

        occurred_at = self._clock.now()
        point = RuntimeTimeRange.point(occurred_at)
        direct_text_indices = self._direct_text_indices(message, transcribed=transcribed)
        final_observations: list[EnvObservation] = []

        for index, content in enumerate(message_content(message)):
            if index in direct_text_indices and isinstance(content, str) and content.strip():
                metadata = {
                    "message_id": message.id,
                    "content_index": index,
                    "input_origin": "direct_text",
                    "entrypoint": "livekit",
                }
                final_observations.append(
                    EnvObservation.text_input(
                        time_range=point,
                        source_id="entrypoint:livekit:text",
                        payload=TextPayload.create(text=content, metadata=dict(metadata)),
                        metadata=metadata,
                    )
                )
            elif isinstance(content, llm.ImageContent):
                final_observations.append(
                    image_content_to_observation(
                        content,
                        clock=self._clock,
                        message_id=message.id,
                        content_index=index,
                        at=occurred_at,
                    )
                )

            elif isinstance(content, llm.AudioContent):
                observation = audio_content_to_observation(
                    content,
                    clock=self._clock,
                    message_id=message.id,
                    content_index=index,
                    at=occurred_at,
                )
                if observation is not None:
                    final_observations.append(observation)

        return self._turn_runtime.commit_input(
            input_id=message.id,
            modality=self._modality(
                message,
                direct_text_indices=direct_text_indices,
                transcribed=transcribed,
            ),
            text=message.text_content,
            final_observations=final_observations,
            metadata={"source": source, "livekit_message_created_at": message.created_at},
        )

    def commit_chat_context(self, chat_ctx: llm.ChatContext, *, source: str) -> TurnSnapshot | None:
        message = self.latest_user_message(chat_ctx)
        return self.commit_message(message, source=source) if message is not None else None
