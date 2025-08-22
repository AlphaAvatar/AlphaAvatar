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
from livekit.agents.types import NotGivenOr

from alphaavatar.agents.configs import AvatarConfig
from alphaavatar.agents.memory import MemoryBase
from alphaavatar.agents.template import AvatarPromptTemplate


class AvatarEngine(Agent):
    def __init__(self, avatar_config: AvatarConfig) -> None:
        system_prompt = AvatarPromptTemplate.init_system_prompt(
            avatar_introduction=avatar_config.prompt_config.avatar_introduction,
        )

        self.avatar_config = avatar_config

        self._memory = avatar_config.memory_config.get_memory_plugin(
            avater_name=avatar_config.prompt_config.avatar_name
        )

        super().__init__(
            instructions=system_prompt,
            turn_detection=avatar_config.livekit_plugin_config.get_turn_detection_plugin(),
            stt=avatar_config.livekit_plugin_config.get_stt_plugin(),
            vad=avatar_config.livekit_plugin_config.get_vad_plugin(),
            llm=avatar_config.livekit_plugin_config.get_llm_plugin(),
            tts=avatar_config.livekit_plugin_config.get_tts_plugin(),
            allow_interruptions=avatar_config.livekit_plugin_config.allow_interruptions,
        )

    @property
    def memory(self) -> NotGivenOr[MemoryBase | None]:
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
        await self.memory.add(turn_ctx, new_message)
        avatar_memeories_str = await self.memory.search(query=new_message.text_content)
        print(
            avatar_memeories_str,
            turn_ctx.items,
            "User turn completed:",
            new_message.content,
            "((--))",
            flush=True,
        )

    async def on_exit(self):
        print("Avatar is exiting...", flush=True)
