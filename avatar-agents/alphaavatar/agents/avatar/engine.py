"""Avatar Launch Engine"""
from livekit.agents import Agent, llm
from livekit.agents.types import NotGivenOr

from alphaavatar.agents.configs import AvatarConfig
from alphaavatar.agents.memory import Memory
from alphaavatar.agents.template import AvatarPromptTemplate


class AvatarEngine(Agent):
    def __init__(self, avatar_config: AvatarConfig) -> None:
        system_prompt = AvatarPromptTemplate.init_system_prompt(
            avatar_introduction=avatar_config.prompt_config.avatar_introduction,
        )

        self.avatar_config = avatar_config
        # self._memory = memory

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
    def memory(self) -> NotGivenOr[Memory | None]:
        """Get the memory instance."""
        return self._memory

    # async def on_user_turn_completed(
    #     self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage
    # ) -> None:
    #     """Override [livekit.agents.voice.agent.Agent::on_user_turn_completed] method to handle user turn completion."""
    #     avatar_memeories_str = self.memory.search(query=new_message.text_content())
    #     print(avatar_memeories_str, turn_ctx.items, "User turn completed:", new_message.content, "((--))", flush=True)
