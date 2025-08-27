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

from livekit.agents import Agent, llm

from alphaavatar.agents.configs import AvatarConfig, SessionConfig
from alphaavatar.agents.memory import MemoryBase
from alphaavatar.agents.template import AvatarPromptTemplate

from .wrapper import add_message_wrapper


class AvatarEngine(Agent):
    def __init__(self, *, session_config: SessionConfig, avatar_config: AvatarConfig) -> None:
        self.session_config = session_config
        self.avatar_config = avatar_config

        self._memory: MemoryBase = avatar_config.memory_config.get_memory_plugin(
            avater_name=avatar_config.avatar_info.avatar_name,
            avatar_id=avatar_config.avatar_info.avatar_id,
        )

        # Prepare initial instructions
        instructions = AvatarPromptTemplate.init_instructions(
            avatar_introduction=self.avatar_config.avatar_info.avatar_introduction,
        )
        super().__init__(
            instructions=instructions,
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
        # Init User & Avatar Interactive Memory by user_id & session_id
        self._memory.init_cache(
            session_id=self.session_config.session_id,
            user_id=self.session_config.user_id,
        )

        # wrap chat context's add_message method to log messages
        self._chat_ctx.add_message = add_message_wrapper(
            session_id=self.session_config.session_id,
            _chat_ctx=self._chat_ctx,
            _memory=self._memory,
        )

    @property
    def memory(self) -> MemoryBase:
        """Get the memory instance."""
        return self._memory

    async def on_enter(self):
        self.session.generate_reply(
            instructions="Briefly greet the user and offer your assistance."
        )

    async def on_user_turn_completed(
        self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage
    ) -> None:
        """Override [livekit.agents.voice.agent.Agent::on_user_turn_completed] method to handle user turn completion."""
        # avatar_memeories_str = await self.memory.search(query=new_message.text_content)
        print(turn_ctx.items, "((-1-1-))", flush=True)
        # print(
        #     avatar_memeories_str,
        #     turn_ctx.items,
        #     "User turn completed:",
        #     new_message.content,
        #     "((--))",
        #     flush=True,
        # )
        pass

    async def on_exit(self):
        await self.memory.update(session_id=self.session_config.session_id)
