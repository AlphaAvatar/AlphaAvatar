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

from functools import partial

from livekit.agents import Agent, RunContext, function_tool, llm

from alphaavatar.agents.configs import AvatarConfig, SessionConfig
from alphaavatar.agents.memory import MemoryBase, memory_chat_context_watcher
from alphaavatar.agents.template import AvatarPromptTemplate

from .chat_context_observer import attach_items_observer


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

        # attach chat context observer
        attach_items_observer(
            ctx=self._chat_ctx,
            on_change=partial(
                memory_chat_context_watcher, self._memory, self.session_config.session_id
            ),
        )

    @property
    def memory(self) -> MemoryBase:
        """Get the memory instance."""
        return self._memory

    @function_tool()
    async def lookup_conversation_memory(
        self,
        context: "RunContext",
        current_user_message: str,
        now_iso: str,
    ) -> str:
        """
        Use this tool to retrieve assistant↔user conversation memories that improve
        personalization and continuity of the current reply.

        CALL THIS TOOL IF ANY OF THE FOLLOWING ARE TRUE:
        {memory_prompt}

        INPUT FIELDS:
        - current_user_message: raw user text for semantic matching.
        - conversation_id: stable ID for long-term storage (optional).
        - recent_turns: last N turns (optional, improves relevance).
        - now_iso: ISO timestamp to enable recency weighting (optional).
        - top_k: max number of memories to return (default 5).
        """
        # ------------------ implementation sketch ------------------
        # 1) Resolve time
        # _now = now_iso or datetime.utcnow().isoformat()

        # 2) (Pseudo) perform semantic retrieval from your memory store
        # candidates = memory_store.search_conversation(conversation_id, current_user_message, recent_turns)

        # 3) (Pseudo) score + filter + redact
        # scored = score_candidates(candidates, _now)
        # top = take_top_k_and_redact(scored, top_k)

        # 4) Stub return with the required shape (replace with real data)
        return ""

    @function_tool()
    async def lookup_tools_memory(
        self,
        context: "RunContext",
        current_user_message: str,
        now_iso: str,
    ):
        """
        Use this tool to recall assistant↔tools interaction memories that help you
        SELECT THE RIGHT TOOL and CONFIGURE IT CORRECTLY for the current task.

        CALL THIS TOOL IF ANY OF THE FOLLOWING ARE TRUE:
        {memory_prompt}

        INPUT FIELDS:
        - current_user_message: raw user text that describes the need.
        - task_intent: pre-parsed task intent if available (optional).
        - tool_catalog: brief list of available tools and capabilities (optional).
        - conversation_id: to scope previous tool runs (optional).
        - now_iso: ISO timestamp for recency weighting (optional).
        - top_k: max number of supporting memories to return (default 5).
        """
        # ------------------ implementation sketch ------------------
        # _now = now_iso or datetime.utcnow().isoformat()

        # candidates = memory_store.search_tools(intention=task_intent or current_user_message)

        # ranked = rank_by_success_and_recency(candidates, _now)
        # top = ranked[:top_k]
        # recommendation = synthesize_recommendation(top, tool_catalog)

        return {
            "recommendation": {
                "tool": "",
                "why": "No relevant tools memory found.",
                "parameters": {},
            },
            "supporting_memories": [],
            "constraints": {"rate_limits": "", "env": "unknown", "known_errors_and_fixes": []},
            "cache_hint": {"usable": False, "cache_key": "", "note": ""},
        }

    async def on_enter(self):
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
        ...

    async def on_exit(self):
        await self.memory.update(session_id=self.session_config.session_id)
