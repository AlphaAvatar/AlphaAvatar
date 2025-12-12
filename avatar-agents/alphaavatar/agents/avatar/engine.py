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
"""Avatar Launch Engine"""

import inspect
from collections.abc import AsyncIterable, Coroutine
from typing import Any

from livekit import rtc
from livekit.agents import Agent, ModelSettings, llm, stt
from livekit.agents.voice.generation import update_instructions

from alphaavatar.agents.configs import AvatarConfig, SessionConfig
from alphaavatar.agents.memory import MemoryBase
from alphaavatar.agents.persona import PersonaBase, speaker_node
from alphaavatar.agents.utils import AvatarTime, format_current_time

from .context import init_context_manager
from .context.template import AvatarPromptTemplate
from .patches import init_avatar_patches  # NOTE: patches import only be used here


class AvatarEngine(Agent):
    def __init__(self, *, session_config: SessionConfig, avatar_config: AvatarConfig) -> None:
        # Step1: initial config
        self.session_config = session_config
        self.avatar_config = avatar_config

        # Step2: initial params
        self._avatar_activate_time: AvatarTime = format_current_time()
        self._avatar_prompt_template = AvatarPromptTemplate(
            self.avatar_config.avatar_info.avatar_introduction,
            current_time=self._avatar_activate_time.time_str,
        )

        # Step3: initial plugins
        self._memory: MemoryBase = avatar_config.memory_config.get_plugin()
        self._persona: PersonaBase = avatar_config.persona_config.get_plugin()
        self._tools: list[llm.FunctionTool | llm.RawFunctionTool] = (
            avatar_config.tools_config.get_tools()
        )

        # Step4: initial avatar
        super().__init__(
            instructions=self._avatar_prompt_template.instructions(),
            turn_detection=self.avatar_config.livekit_plugin_config.get_turn_detection_plugin(),
            stt=self.avatar_config.livekit_plugin_config.get_stt_plugin(),
            vad=self.avatar_config.livekit_plugin_config.get_vad_plugin(),
            llm=self.avatar_config.livekit_plugin_config.get_llm_plugin(),
            tts=self.avatar_config.livekit_plugin_config.get_tts_plugin(),
            allow_interruptions=self.avatar_config.livekit_plugin_config.allow_interruptions,
            tools=self._tools,
        )

    @property
    def template(self) -> AvatarPromptTemplate:
        return self._avatar_prompt_template

    @property
    def memory(self) -> MemoryBase:
        """Get the memory instance."""
        return self._memory

    @property
    def persona(self) -> PersonaBase:
        """Get the memory instance."""
        return self._persona

    async def on_enter(self):
        # BUG: Before entering the function to send a greeting, the front end allows the user to input, but the system cannot recognize it.

        # Init User & Avatar Interactive Memory by init user_id & session_id
        await self._memory.init_cache(
            session_id=self.session_config.session_id,
            user_or_tool_id=self.session_config.user_id,
        )

        # Init User Peronsa by init user_id
        await self._persona.init_cache(
            timestamp=self._avatar_activate_time, init_user_id=self.session_config.user_id
        )

        init_avatar_patches(self)
        init_context_manager(self)

        self.session.generate_reply(
            instructions="Briefly greet the user and offer your assistance."
        )

    def stt_node(
        self, audio: AsyncIterable[rtc.AudioFrame], model_settings: ModelSettings
    ) -> (
        AsyncIterable[stt.SpeechEvent | str]
        | Coroutine[Any, Any, AsyncIterable[stt.SpeechEvent | str]]
        | Coroutine[Any, Any, None]
    ):
        """
        STT [stt_node] -> Text -> Text append to chat context -> chat context -> llm

        Override [livekit.agents.voice.agent.Agent::stt_node] method to handle audio inputs.
        """

        async def preprocess_audio():
            async for frame in audio:
                # insert custom audio preprocessing here
                yield frame

        return speaker_node(self, preprocess_audio(), model_settings)

    async def on_user_turn_completed(
        self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage
    ) -> None:
        """
        STT -> Text [on_user_turn_completed] -> Text append to chat context

        Override [livekit.agents.voice.agent.Agent::on_user_turn_completed] method to handle user turn completion.
        """
        # BUG: When multiple separate user messages are entered consecutively, LiveKit will only use the latest one.
        ...

    def llm_node(
        self,
        chat_ctx: llm.ChatContext,
        tools: list[llm.FunctionTool | llm.RawFunctionTool],
        model_settings: ModelSettings,
    ) -> (
        AsyncIterable[llm.ChatChunk | str]
        | Coroutine[Any, Any, AsyncIterable[llm.ChatChunk | str]]
        | Coroutine[Any, Any, str]
        | Coroutine[Any, Any, llm.ChatChunk]
        | Coroutine[Any, Any, None]
    ):
        """
        STT -> Text -> Text append to chat context -> chat context [llm_node] -> llm

        Override [livekit.agents.voice.agent.Agent::llm_node] method to handle llm inputs.
        """

        async def _gen() -> AsyncIterable[llm.ChatChunk | str]:
            await self._chat_ctx.items.wait_pending()  # type: ignore

            # The current chat_ctx is temporarily copied from self._chat_ctx
            update_instructions(
                chat_ctx,
                instructions=self.template.instructions(
                    memory_content=self.memory.memory_content,
                    user_persona=self.persona.persona_content,
                ),
                add_if_missing=True,
            )

            res = Agent.default.llm_node(self, chat_ctx, tools, model_settings)

            if inspect.isawaitable(res):
                res = await res

            # 如果是 AsyncIterable，逐个转发
            if hasattr(res, "__aiter__"):
                async for chunk in res:  # type: ignore[attr-defined]
                    yield chunk
                return

            if isinstance(res, str | llm.ChatChunk):
                yield res
                return

            return

        return _gen()

    async def on_exit(self):
        # memory op
        await self.memory.update(avatar_id=self.avatar_config.avatar_info.avatar_id)
        await self.memory.save()

        # persona op
        await self.persona.update_profile_details()
        await self.persona.save()
