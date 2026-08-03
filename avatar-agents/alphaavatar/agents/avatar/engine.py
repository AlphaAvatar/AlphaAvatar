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
import inspect
from collections.abc import AsyncIterable, Callable, Sequence
from typing import Any
from uuid import uuid4

from livekit import rtc
from livekit.agents import Agent, ModelSettings, llm, stt as livekit_stt, tts as livekit_tts
from livekit.agents.types import FlushSentinel

from alphaavatar.agents.configs import AvatarConfig
from alphaavatar.agents.entrypoints.schema.room_type import RoomType
from alphaavatar.agents.interaction import InteractionRouterBase
from alphaavatar.agents.log import logger
from alphaavatar.agents.memory import MemoryBase
from alphaavatar.agents.persona import PersonaBase
from alphaavatar.agents.plugin import AvatarModule, AvatarRuntimePlugin
from alphaavatar.agents.runtime import (
    AvatarRuntime,
    ContextRuntime,
    SessionRuntime,
)
from alphaavatar.agents.status import (
    StatusEmitter,
    StatusEvent,
    StatusType,
)
from alphaavatar.core.output import OutputLane
from alphaavatar.core.perception import PerceptionRuntime

from .context import init_context_manager
from .context.internal_tools import get_runtime_context_tool
from .lifecycle import LifecyclePhase, RuntimePluginLifecycle
from .patches import init_avatar_patches
from .prompting.assembler import PromptAssembler
from .prompting.model_call import (
    AvatarModelContextBuilder,
    ModelCallStatus,
    extract_answer_text,
)
from .prompting.template import AvatarSysPromptTemplate, RuntimeContextTemplate
from .vision import VisionBase, build_vision
from .voice import LiveKitSTTBridge, LiveKitTranscriptionAdapter, LiveKitTTSAdapter


class AvatarEngine(Agent):
    def __init__(
        self,
        *,
        avatar_config: AvatarConfig,
        runtime: AvatarRuntime,
        rtc_plugins: dict[str, Sequence[AvatarRuntimePlugin]],
    ) -> None:
        self.avatar_config = avatar_config
        self.runtime = runtime
        self._rtc_plugins = rtc_plugins

        # Step 1: initialize prompt components.
        #
        # The system template is required by Agent.__init__, so it must be
        # created before super().__init__().
        self._avatar_prompt_template = AvatarSysPromptTemplate(
            self.avatar_config.avatar.introduction,
            interaction_method=self.context_runtime.interaction_method,
            stable_behavior_rules=self.context_runtime.global_behavior_rules,
        )
        self._runtime_context_template = RuntimeContextTemplate()
        self._prompt_assembler = PromptAssembler(
            injection_mode=self.avatar_config.runtime.context_mode,
        )

        # Step 2: initialize the temporary AlphaAvatar STT -> LiveKit bridge.
        self._livekit_transcription_adapter = LiveKitTranscriptionAdapter()

        # Step 3: initialize runtime plugins and tools.
        self._livekit_tts: livekit_tts.TTS | None = avatar_config.voice.get_tts_plugin()
        self._tts = (
            LiveKitTTSAdapter(self._livekit_tts, owns_provider=False)
            if self._livekit_tts is not None
            else None
        )
        self._status: StatusEmitter = avatar_config.status.get_plugin(
            runtime=self.runtime,
        )
        self._router: InteractionRouterBase = avatar_config.router.get_plugin(
            runtime=self.runtime,
            vad=avatar_config.voice.get_vad_plugin(
                inference_executor=self.runtime.inference,
            ),
            stt=avatar_config.voice.get_stt_plugin(),
            tts=self._tts,
            on_transcription=self._livekit_transcription_adapter.handle_event,
        )
        self._memory: MemoryBase = avatar_config.memory.get_plugin(
            runtime=self.runtime,
            avatar_id=self.avatar_config.avatar.id,
        )
        self._persona: PersonaBase = avatar_config.persona.get_plugin(self.runtime)
        self._tools: list[llm.FunctionTool | llm.RawFunctionTool] = avatar_config.tools.get_tools(
            self.runtime,
            status_emitter=self._status,
        )
        self._tools.append(get_runtime_context_tool())

        # Step 4: initialize the underlying LiveKit Agent.
        super().__init__(
            instructions=self._avatar_prompt_template.instructions(),
            llm=self.avatar_config.llm.get_plugin(),
            turn_detection=self.avatar_config.voice.get_turn_detection_plugin(),
            stt=LiveKitSTTBridge(),
            vad=self.avatar_config.voice.get_legacy_livekit_vad_plugin(),
            tts=self._livekit_tts,
            allow_interruptions=self.avatar_config.voice.allow_interruptions,
            tools=self._tools,
        )

        # Step 5: bind components that require a fully initialized Agent.
        self._vision: VisionBase = build_vision(self)

        # Step 6: configure staged plugin lifecycle.
        #
        # Consumers start concurrently before any producer is allowed to publish.
        # During shutdown, producers stop concurrently before consumers stop.
        self._plugin_lifecycle = RuntimePluginLifecycle(
            phases=(
                LifecyclePhase.create(
                    "rtc_outputs",
                    tuple(self._rtc_plugins.get("outputs", ())),
                ),
                LifecyclePhase.create(
                    "perception_consumers",
                    (
                        self._persona,
                        self._memory,
                        self._vision,
                    ),
                ),
                LifecyclePhase.create(
                    "interaction_router",
                    (self._router,),
                ),
                LifecyclePhase.create(
                    "rtc_inputs",
                    tuple(self._rtc_plugins.get("inputs", ())),
                ),
            )
        )

        # Step 7: initialize per-call model context preparation.
        self._model_context_builder = AvatarModelContextBuilder(
            context_runtime=self.context_runtime,
            memory=self._memory,
            persona=self._persona,
            vision=self._vision,
            system_template=self._avatar_prompt_template,
            runtime_context_template=self._runtime_context_template,
            prompt_assembler=self._prompt_assembler,
        )

    @property
    def session_runtime(self) -> SessionRuntime:
        return self.runtime.session

    @property
    def context_runtime(self) -> ContextRuntime:
        return self.runtime.context

    @property
    def perception_runtime(self) -> PerceptionRuntime:
        return self.runtime.perception

    @property
    def memory(self) -> MemoryBase:
        """Get the memory instance."""
        return self._memory

    @property
    def persona(self) -> PersonaBase:
        """Get the memory instance."""
        return self._persona

    """Helper Op"""

    @staticmethod
    async def _run_shutdown_step(
        label: str,
        operation: Callable[[], Any],
        errors: list[Exception],
    ) -> None:
        try:
            result = operation()

            if inspect.isawaitable(result):
                await result

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "AvatarEngine shutdown step failed: %s",
                label,
            )

            error = RuntimeError(f"AvatarEngine shutdown step failed: {label}")
            error.__cause__ = exc
            errors.append(error)

    @staticmethod
    async def _call_with_supported_kwargs(
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        try:
            signature = inspect.signature(func)
        except (TypeError, ValueError):
            # Some extension or dynamically generated callables do not expose
            # an inspectable signature.
            supported_kwargs = kwargs
        else:
            parameters = signature.parameters

            accepts_arbitrary_kwargs = any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
            )

            if accepts_arbitrary_kwargs:
                supported_kwargs = kwargs
            else:
                keyword_parameters = {
                    name
                    for name, parameter in parameters.items()
                    if parameter.kind
                    in {
                        inspect.Parameter.POSITIONAL_OR_KEYWORD,
                        inspect.Parameter.KEYWORD_ONLY,
                    }
                }

                supported_kwargs = {
                    key: value for key, value in kwargs.items() if key in keyword_parameters
                }

        result = func(*args, **supported_kwargs)

        if inspect.isawaitable(result):
            return await result

        return result

    """Base Op"""

    async def speak_status_text(
        self,
        text: str,
        *,
        allow_interruptions: bool = True,
        add_to_chat_ctx: bool = False,
    ) -> None:
        """
        Speak a short status message without going through the LLM.

        This is for intermediate status only:
        - interruptible by user input
        - interruptible by normal assistant speech
        - not added to chat context
        """
        session = getattr(self, "session", None)
        if session is None:
            logger.debug("Cannot speak status text because session is unavailable.")
            return

        say = getattr(session, "say", None)
        if not callable(say):
            logger.debug("Cannot speak status text because session.say is unavailable.")
            return

        try:
            handle = await self._call_with_supported_kwargs(
                say,
                text,
                allow_interruptions=allow_interruptions,
                add_to_chat_ctx=add_to_chat_ctx,
            )

            if handle is not None and inspect.isawaitable(handle):
                await handle

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug("Status speech failed or was interrupted: %s", e)

    async def on_enter(self) -> None:
        init_avatar_patches(self)
        init_context_manager(self)

        await self._plugin_lifecycle.start()

        if self.context_runtime.interaction_method.room_type == RoomType.WEB_APP.value:
            self._status.emit_nowait(
                StatusEvent(
                    type=StatusType.READY,
                    source=AvatarModule.AVATAR_ENGINE,
                    stage="session_ready",
                )
            )

    async def on_exit(self) -> None:
        errors: list[Exception] = []

        wait_pending = getattr(
            getattr(self._chat_ctx, "items", None),
            "wait_pending",
            None,
        )

        if callable(wait_pending):
            await self._run_shutdown_step(
                "chat context pending flush",
                wait_pending,
                errors,
            )

        await self._run_shutdown_step(
            "runtime plugin shutdown",
            self._plugin_lifecycle.stop,
            errors,
        )

        await self._run_shutdown_step(
            "avatar runtime shutdown",
            self.runtime.aclose,
            errors,
        )

        await self._run_shutdown_step(
            "session user path migration flush",
            lambda: self.session_runtime.flush_user_path_migrations(
                remove_old=True,
            ),
            errors,
        )

        if errors:
            raise ExceptionGroup(
                "AvatarEngine shutdown completed with errors.",
                errors,
            )

    """Node Op"""

    def stt_node(
        self,
        audio: AsyncIterable[rtc.AudioFrame],
        model_settings: ModelSettings,
    ) -> AsyncIterable[livekit_stt.SpeechEvent]:
        """
        Temporary AlphaAvatar STT -> LiveKit turn-handling bridge.

        AlphaAvatar owns transcription inference. LiveKit continues to own
        turn detection, endpointing and user-turn commitment in v0.6.5.
        """
        return self._livekit_transcription_adapter.stream(audio)

    def llm_node(
        self,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool],
        model_settings: ModelSettings,
    ) -> AsyncIterable[llm.ChatChunk | str | FlushSentinel]:
        async def _generate():
            prepared = self._model_context_builder.prepare(chat_ctx)

            model_call_status = ModelCallStatus(
                emitter=self._status,
                input_kind=prepared.input_kind,
            )
            await model_call_status.start()

            assistant_output_id = uuid4().hex
            assistant_text_started = False

            try:
                async for chunk in Agent.default.llm_node(
                    self,
                    prepared.chat_ctx,
                    tools,
                    model_settings,
                ):
                    await model_call_status.on_chunk(chunk)

                    text = extract_answer_text(chunk)
                    if text is not None:
                        assistant_text_started = True

                        # During the migration period this mirrors the text stream.
                        # AgentSession still performs the actual final TTS.
                        await self.runtime.output.publish_text_chunk(
                            text=text,
                            output_id=assistant_output_id,
                            turn_id=model_call_status.turn_id,
                            lane=OutputLane.ASSISTANT,
                        )

                    yield chunk

            finally:
                if assistant_text_started:
                    await self.runtime.output.complete(
                        lane=OutputLane.ASSISTANT,
                        output_id=assistant_output_id,
                        turn_id=model_call_status.turn_id,
                    )

                await model_call_status.close()

        return _generate()
