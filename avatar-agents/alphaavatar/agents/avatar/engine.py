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
from functools import partial
from typing import Any

from livekit.agents import Agent, ModelSettings, RunContext, function_tool, llm
from livekit.agents.voice.generation import update_instructions

from alphaavatar.agents.configs import AvatarConfig, SessionConfig
from alphaavatar.agents.memory import MemoryBase, memory_chat_context_watcher, memory_search_hook
from alphaavatar.agents.persona import PersonaBase, persona_chat_context_watcher
from alphaavatar.agents.template import AvatarPromptTemplate
from alphaavatar.agents.utils import format_current_time

from .avatar_hooks import HookRegistry, install_generation_hooks
from .chat_context_observer import attach_observer


class AvatarEngine(Agent):
    def __init__(self, *, session_config: SessionConfig, avatar_config: AvatarConfig) -> None:
        # initial config
        self.session_config = session_config
        self.avatar_config = avatar_config

        # initial plugins
        self._memory: MemoryBase = avatar_config.memory_config.get_memory_plugin(
            avater_name=avatar_config.avatar_info.avatar_name,
            avatar_id=avatar_config.avatar_info.avatar_id,
        )
        self._persona: PersonaBase = avatar_config.persona_config.get_persona_plugin()

        # initial params
        self._avatar_create_time = format_current_time(
            self.avatar_config.avatar_info.avatar_timezone
        )
        self._avatar_prompt_template = AvatarPromptTemplate(
            self.avatar_config.avatar_info.avatar_introduction,
            current_time=self._avatar_create_time["time_str"],
        )

        # initial avatar
        super().__init__(
            instructions=self._avatar_prompt_template.instructions(),
            turn_detection=self.avatar_config.livekit_plugin_config.get_turn_detection_plugin(),
            stt=self.avatar_config.livekit_plugin_config.get_stt_plugin(),
            vad=self.avatar_config.livekit_plugin_config.get_vad_plugin(),
            llm=self.avatar_config.livekit_plugin_config.get_llm_plugin(),
            tts=self.avatar_config.livekit_plugin_config.get_tts_plugin(),
            allow_interruptions=self.avatar_config.livekit_plugin_config.allow_interruptions,
        )

        self.__post_init__()

    def __post_init__(self):
        """Post-initialization to Avtar."""
        # Init User & Avatar Interactive Memory by init user_id & session_id
        self._memory.init_cache(
            timestamp=self._avatar_create_time,
            session_id=self.session_config.session_id,
            user_or_tool_id=self.session_config.user_id,
        )

        # Init User Peronsa by init user_id
        self._persona.init_cache(user_id=self.session_config.user_id)

        # attach memory chat context observer
        attach_observer(
            ctx=self._chat_ctx,
            on_change=partial(
                memory_chat_context_watcher, self._memory, self.session_config.session_id
            ),
        )
        attach_observer(
            ctx=self._chat_ctx,
            on_change=partial(
                persona_chat_context_watcher, self._persona, self.session_config.user_id
            ),
        )

        # generation hooks
        self._generation_hooks = HookRegistry()
        self._generation_hook_installed = False
        self._generation_hooks.add(
            partial(memory_search_hook, self._memory, self.session_config.session_id),
            name="memory_search",
            priority=1,
        )

    @property
    def memory(self) -> MemoryBase:
        """Get the memory instance."""
        return self._memory

    @property
    def persona(self) -> PersonaBase:
        """Get the memory instance."""
        return self._persona

    @function_tool()
    async def recall_memory(
        self,
        context: RunContext,
        location: str,
    ) -> dict[str, Any]:
        """Look up weather information for a given location.

        Args:
            location: The location to look up weather information for.
        """
        # TODO: user ask agent recall memory
        return {"weather": "sunny", "temperature_f": 70}

    async def on_enter(self):
        # BUG: Before entering the function to send a greeting, the front end allows the user to input, but the system cannot recognize it.
        install_generation_hooks(self)
        self.session.generate_reply(
            instructions="Briefly greet the user and offer your assistance."
        )

    async def on_user_turn_completed(
        self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage
    ) -> None:
        """
        TTS -> Text [on_user_turn_completed] -> Text append to chat context

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
        TTS -> Text -> Text append to chat context -> chat context [llm_node] -> llm

        Override [livekit.agents.voice.agent.Agent::llm_node] method to handle llm inputs.
        """

        async def _gen() -> AsyncIterable[llm.ChatChunk | str]:
            await self._chat_ctx.items.wait_pending()  # type: ignore

            # The current chat_ctx is temporarily copied from self._chat_ctx
            update_instructions(
                chat_ctx,
                instructions=self._avatar_prompt_template.instructions(
                    memory_content=self.memory.memory_content,
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
        await self.memory.update()

        # persona op
        await self.persona.update()
