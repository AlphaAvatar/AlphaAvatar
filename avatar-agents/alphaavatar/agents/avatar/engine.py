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

import asyncio
import os
from collections.abc import AsyncIterable, Coroutine
from contextlib import suppress
from typing import Any

from livekit import rtc
from livekit.agents import Agent, ModelSettings, llm, stt
from livekit.agents.types import FlushSentinel
from livekit.agents.voice.generation import update_instructions

from alphaavatar.agents.configs import AvatarConfig, SessionConfig
from alphaavatar.agents.constants import DEFAULT_SYSTEM_VALUE
from alphaavatar.agents.log import logger
from alphaavatar.agents.memory import MemoryBase
from alphaavatar.agents.persona import PersonaBase, speaker_node
from alphaavatar.agents.status import (
    StatusEmitter,
    StatusEvent,
    StatusType,
    StatusVisibility,
)
from alphaavatar.agents.utils import AvatarTime, format_current_time
from alphaavatar.agents.utils.files.work_dirs import (
    UserPathSnapshot,
    migrate_user_path,
    mk_user_dirs,
)

from .context import init_context_manager
from .context.internal_tools import get_runtime_context_tool
from .context.runtime_context import AvatarRuntimeContext
from .patches import init_avatar_patches  # NOTE: patches import only be used here
from .prompting.assembler import PromptAssembler
from .prompting.template import AvatarSysPromptTemplate, RuntimeContextTemplate
from .vision import VisionBase, build_vision


class AvatarEngine(Agent):
    def __init__(
        self,
        *,
        session_config: SessionConfig,
        avatar_config: AvatarConfig,
        runtime_context: AvatarRuntimeContext | None = None,
    ) -> None:
        # Step1: initial config
        self.session_config = session_config
        self.avatar_config = avatar_config
        self.runtime_context = runtime_context or AvatarRuntimeContext()

        # Step2: initial params
        self._avatar_activate_time: AvatarTime = format_current_time(
            self.runtime_context.time_context.current_timezone
            if self.runtime_context.time_context.current_timezone != "Unknown"
            else None
        )

        self._avatar_prompt_template = AvatarSysPromptTemplate(
            self.avatar_config.avatar_info.avatar_introduction,
            interaction_method=self.runtime_context.interaction_method,
            stable_behavior_rules=self.runtime_context.global_behavior_rules,
        )

        self._runtime_context_template = RuntimeContextTemplate()
        self._prompt_assembler = PromptAssembler(
            injection_mode=self.avatar_config.runtime_config.runtime_context_mode,
        )

        # Status emitter
        self.status_emitter: StatusEmitter = avatar_config.status_config.get_plugin()

        # Step3: initial plugins
        self._memory: MemoryBase = avatar_config.memory_config.get_plugin(self.session_config)
        self._persona: PersonaBase = avatar_config.persona_config.get_plugin(self.session_config)
        self._tools: list[llm.FunctionTool | llm.RawFunctionTool] = (
            avatar_config.tools_config.get_tools(
                self.session_config,
                status_emitter=self.status_emitter,
            )
        )
        self._tools.append(get_runtime_context_tool())

        # Step4: initial avatar
        super().__init__(
            instructions=self.system_template.instructions(),
            # llm
            llm=self.avatar_config.llm_config.get_plugin(),
            # voice plugins
            turn_detection=self.avatar_config.voice_config.get_turn_detection_plugin(),
            stt=self.avatar_config.voice_config.get_stt_plugin(),
            vad=self.avatar_config.voice_config.get_vad_plugin(),
            tts=self.avatar_config.voice_config.get_tts_plugin(),
            allow_interruptions=self.avatar_config.voice_config.allow_interruptions,
            # tools
            tools=self._tools,
        )

        # Bind runtime engine to status components.
        self.status_emitter.bind_engine(self)

        # vision
        self._vision: VisionBase = build_vision(self)

        # other states
        self._pending_user_path_migration: tuple[UserPathSnapshot, UserPathSnapshot] | None = None

    @property
    def memory(self) -> MemoryBase:
        """Get the memory instance."""
        return self._memory

    @property
    def persona(self) -> PersonaBase:
        """Get the memory instance."""
        return self._persona

    @property
    def system_template(self) -> AvatarSysPromptTemplate:
        return self._avatar_prompt_template

    @property
    def runtime_context_template(self) -> RuntimeContextTemplate:
        return self._runtime_context_template

    @property
    def prompt_assembler(self) -> PromptAssembler:
        return self._prompt_assembler

    def _sync_runtime_context_for_turn(self) -> None:
        """
        Sync plugin-produced context into AvatarRuntimeContext.

        Note:
        user_persona is system-level context, but it may become available after
        the session starts, for example after speaker/user identity is resolved.
        Therefore, we refresh it every turn and let the system prompt update when needed.
        """

        # 1. Refresh current time for this turn.
        current_timezone = self.runtime_context.time_context.current_timezone
        if current_timezone and current_timezone != "Unknown":
            current = format_current_time(current_timezone)
            self.runtime_context.time_context.current_time = current.time_str
            self.runtime_context.time_context.current_timezone = current.timezone

        # 2. Refresh persona every turn.
        #
        # Persona belongs to system prompt, but it can be empty at session start
        # and become available after user/speaker identification.
        self.runtime_context.user_persona = self.persona.persona_content or DEFAULT_SYSTEM_VALUE

        # 3. Dynamic memory for current turn.
        self.runtime_context.memory_content = self.memory.memory_content or DEFAULT_SYSTEM_VALUE

        # 4. Dynamic plan / reflection / turn behavior rules.
        #
        # TODO:
        # Replace these with plugin values when behavior/plan/reflection plugins are added.
        self.runtime_context.plan_content = (
            self.runtime_context.plan_content or DEFAULT_SYSTEM_VALUE
        )
        self.runtime_context.reflection_content = (
            self.runtime_context.reflection_content or DEFAULT_SYSTEM_VALUE
        )
        self.runtime_context.turn_behavior_rules = (
            self.runtime_context.turn_behavior_rules or DEFAULT_SYSTEM_VALUE
        )

    async def _finalize_user_path_migration(self) -> None:
        if self._pending_user_path_migration is None:
            return

        old_user_path, new_user_path = self._pending_user_path_migration

        try:
            migrate_user_path(
                old_user_path=old_user_path,
                new_user_path=new_user_path,
                remove_old=True,
            )
            logger.info(
                "Final user path migration success old_path=%s new_path=%s",
                old_user_path.user_root,
                new_user_path.user_root,
            )
            self._pending_user_path_migration = None
        except Exception as e:
            logger.warning("Final user path migration failed: %s", e)

    async def resolve_user_identity(self, *, user_id: str) -> None:
        if not user_id or user_id == self.session_config.user_id:
            return

        old_user_id = self.session_config.user_id
        old_user_path = self.session_config.user_path.snapshot()

        work_dir = os.getenv("AVATAR_WORK_DIR", "")
        new_user_path = mk_user_dirs(work_dir, user_id)
        new_user_snapshot = new_user_path.snapshot()

        # Record pending migration.
        # Do not migrate immediately, because RAG/temp artifacts may still be active.
        self._pending_user_path_migration = (old_user_path, new_user_snapshot)

        # Important:
        # This triggers UserPath callbacks immediately.
        # memory/persona/deepresearch/rag can now see the real user path.
        self.session_config.update_user_id(user_id)

        self.memory.update_user_tool_id(
            ori_id=old_user_id,
            tgt_id=user_id,
        )

        logger.info(
            "Resolved user identity old_user=%s new_user=%s; old_path=%s new_path=%s; migration deferred to on_exit",
            old_user_id,
            user_id,
            old_user_path.user_root,
            new_user_path.user_root,
        )

    async def on_enter(self):
        # BUG: Before entering the function to send a greeting, the front end allows the user to input, but the system cannot recognize it.

        # Init User & Avatar Interactive Memory by init user_id & session_id
        await self._memory.init_cache(
            session_id=self.session_config.session_id,
            user_or_tool_id=self.session_config.user_id,
        )

        # Init User Peronsa by init user_id
        await self._persona.init_cache(
            timestamp=self._avatar_activate_time,
            init_user_id=self.session_config.user_id,
        )

        # Update deterministic runtime/session state.
        self.persona.update_runtime_state(
            uid=self.session_config.user_id,
            current_timezone=self.runtime_context.time_context.current_timezone,
            timezone_source=self.runtime_context.time_context.timezone_source,
            current_login_time=self.runtime_context.time_context.current_time,
            session_id=self.session_config.session_id,
            room_type=self.runtime_context.interaction_method.room_type,
        )

        # init patches and context manager
        init_avatar_patches(self)
        init_context_manager(self)

        # enable vision input if needed
        self._vision.start()

        self.session.generate_reply(user_input="Briefly greet the user and offer your assistance.")

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
        STT -> Text -> [on_user_turn_completed] -> Text append to chat context

        Override [livekit.agents.voice.agent.Agent::on_user_turn_completed] method to handle user turn completion.
        Only Voice Input will call this function, and it is called after the user stops speaking and the final transcription is ready.
        """
        # BUG: When multiple separate user messages are entered consecutively, LiveKit will only use the latest one.
        ...

    def llm_node(
        self,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool],
        model_settings: ModelSettings,
    ) -> AsyncIterable[llm.ChatChunk | str | FlushSentinel]:
        """
        STT -> Text -> Text append to chat context -> chat context [llm_node] -> llm

        Static content stays in system prompt for prefix-cache friendliness.
        Dynamic per-turn context is injected after the latest user query.
        """

        # NOTE: The user query in the `llm_node` is appended after copying the chat_context;
        # it's a temporary state. The user query and answer are only inserted into the
        # chat_context after the answer is generated.

        async def _gen():
            # 0. Reset status policy for this user turn.
            self.status_emitter.start_turn()

            # 1. Sync all plugin-produced context into runtime_context.
            self._sync_runtime_context_for_turn()

            # 2. Render system-level prompt.
            update_instructions(
                chat_ctx,
                instructions=self.system_template.instructions(
                    stable_persona=self.runtime_context.user_persona,
                ),
                add_if_missing=True,
            )

            # 3. Build model-facing context.
            # Original chat_ctx keeps full history.
            model_chat_ctx = self.prompt_assembler.prepare_model_chat_context(
                chat_ctx,
                strip_historical_visuals=True,
                add_visual_placeholder=True,
            )

            # 4. Inject current visual frames into temporary context only.
            self._vision.inject_into_chat_ctx(model_chat_ctx)

            # 5. Render turn-level runtime context.
            runtime_context_text = self.runtime_context_template.render(
                runtime_context=self.runtime_context
            )

            # 6. Inject runtime context after latest user query.
            injected_chat_ctx = self.prompt_assembler.inject_runtime_context(
                model_chat_ctx,
                runtime_context=runtime_context_text,
            )

            # 7. Call model.
            thinking_task = self.status_emitter.emit_delayed(
                StatusEvent(
                    type=StatusType.THINKING,
                    source="avatar_engine",
                    stage="thinking",
                    visibility=StatusVisibility.TEXT,
                    render_mode="auto",
                )
            )

            try:
                async for chunk in Agent.default.llm_node(
                    self,
                    injected_chat_ctx,
                    tools,
                    model_settings,
                ):
                    if thinking_task is not None and not thinking_task.done():
                        thinking_task.cancel()
                        with suppress(asyncio.CancelledError):
                            await thinking_task

                    yield chunk
            finally:
                if thinking_task is not None and not thinking_task.done():
                    thinking_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await thinking_task

        return _gen()

    async def on_exit(self):
        if hasattr(self._chat_ctx.items, "wait_pending"):
            await self._chat_ctx.items.wait_pending()

        # vision cleanup
        await self._vision.stop()

        # memory op
        await self.memory.update(avatar_id=self.avatar_config.avatar_info.avatar_id)
        await self.memory.save()

        # persona op
        await self.persona.update_profile_details()
        await self.persona.save()

        # RAG / temp files cleanup
        await self._finalize_user_path_migration()
