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

import asyncio
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import uuid4

from pydantic import BaseModel, Field

from alphaavatar.agents.memory import MemoryContextState
from alphaavatar.agents.memory.enums import MemoryType
from alphaavatar.agents.providers import ProviderGateway, ProvidersConfig
from alphaavatar.agents.providers.schema import (
    ModelInput,
    ModelInputMessage,
    ModelRole,
    ModelTextPart,
)

from .log import logger
from .memory_op import EnvMemoryDelta, MemoryDelta
from .prompts import ENV_DELTA_PROMPT, TOOL_DELTA_PROMPT, build_conversation_delta_prompt
from .user_memory import (
    CONSOLIDATION_PROMPT,
    SESSION_SUMMARY_PROMPT,
    ConsolidationPlan,
)

if TYPE_CHECKING:
    from .env_memory import EnvMemoryInput

TStructuredOutput = TypeVar("TStructuredOutput", bound=BaseModel)


class MemoryProviderConfig(BaseModel):
    conversation_delta_task: str = "memory.conversation_delta"
    tool_delta_task: str = "memory.tool_delta"
    env_delta_task: str | None = None
    gateway: ProvidersConfig = Field(default_factory=ProvidersConfig)


class MemoryDeltaExtractor:
    def __init__(self, config: MemoryProviderConfig | None = None) -> None:
        self._config = config or MemoryProviderConfig()
        self._conversation_delta_task = self._config.conversation_delta_task
        self._tool_delta_task = self._config.tool_delta_task
        self._env_delta_task = self._config.env_delta_task
        self._provider_gateway = ProviderGateway(self._config.gateway)
        self._provider_gateway.validate_tasks(
            [
                task
                for task in (
                    self._conversation_delta_task,
                    self._tool_delta_task,
                    self._env_delta_task,
                )
                if task
            ]
        )

    @property
    def config(self) -> MemoryProviderConfig:
        return self._config

    @staticmethod
    def base_trace_metadata(
        *,
        context_state: MemoryContextState,
        operation: str,
        memory_type: MemoryType,
        component: str = "memory_delta_extractor",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        context = context_state.context
        metadata = {
            "provider_dir": str(context_state.provider_dir),
            "plugin": "memory",
            "component": component,
            "operation": operation,
            "episode_id": context.episode_id,
            "context_id": context.context_id,
            "session_id": context.session_id,
            "cache_type": context_state.cache_type.value,
            "memory_type": memory_type.value,
        }
        if extra:
            metadata.update(extra)
        return metadata

    def _build_env_model_input(
        self,
        *,
        memory_input: EnvMemoryInput,
        previous_env_memory: str | None,
        conversation_context: str | None,
    ) -> ModelInput:
        instructions = "\n".join(
            (
                "Generate an environment memory delta from the ordered audio-visual timeline.",
                "Output only EnvMemoryDelta.",
                "",
                "The audio track is continuous microphone evidence, not VAD-selected user speech.",
                "Use audio, images and source-state transitions together.",
                "Do not transcribe every sound or describe every frame.",
                "Store only stable, useful or meaningful environmental facts.",
                "Do not invent identities from appearance, voice or local ids.",
                "If there is no useful new memory, return an empty EnvMemoryDelta.",
                "",
                "<previous_env_memory>",
                previous_env_memory or "",
                "</previous_env_memory>",
                "",
                "<conversation_context>",
                conversation_context or "",
                "</conversation_context>",
            )
        )
        return ModelInput(
            items=(
                ModelInputMessage(
                    id=f"memory.env:{uuid4().hex}",
                    role=ModelRole.USER,
                    parts=(ModelTextPart(instructions), memory_input.temporal),
                ),
            )
        )

    async def _safe_ainvoke_structured(
        self,
        *,
        task_name: str,
        prompt: Any,
        payload: dict[str, Any],
        output_schema: type[TStructuredOutput],
        fallback_output: TStructuredOutput,
        metadata: dict[str, Any],
        timeout: float,
        tracing_payload: bool = True,
        raise_on_error: bool = False,
    ) -> TStructuredOutput:
        try:
            result = await asyncio.wait_for(
                self._provider_gateway.ainvoke_structured(
                    task_name=task_name,
                    prompt=prompt,
                    payload=payload,
                    output_schema=output_schema,
                    metadata=metadata,
                    tracing_payload=tracing_payload,
                ),
                timeout=timeout,
            )
            return (
                result.output
                if isinstance(result.output, output_schema)
                else output_schema.model_validate(result.output)
            )
        except TimeoutError:
            logger.warning("[Memory] extraction timeout task=%s timeout=%s", task_name, timeout)
            if raise_on_error:
                raise

            return fallback_output

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("[Memory] extraction failed task=%s error=%s", task_name, exc)
            if raise_on_error:
                raise

            return fallback_output

    async def extract_conversation_delta(
        self,
        *,
        session_content: str,
        context_state: MemoryContextState,
        session_gate: bool = False,
        timeout: float = 12.0,
    ) -> MemoryDelta:
        return await self._safe_ainvoke_structured(
            task_name=self._conversation_delta_task,
            prompt=build_conversation_delta_prompt(session_gate=session_gate),
            payload={"session_content": session_content},
            output_schema=MemoryDelta,
            fallback_output=MemoryDelta(),
            metadata=self.base_trace_metadata(
                context_state=context_state,
                operation="conversation_delta",
                memory_type=MemoryType.CONVERSATION,
            ),
            timeout=timeout,
        )

    async def plan_consolidation(
        self,
        *,
        payload: dict[str, Any],
        session_summary: bool,
        metadata: dict[str, Any],
        timeout: float,
    ) -> ConsolidationPlan:
        return await self._safe_ainvoke_structured(
            task_name=self._conversation_delta_task,
            prompt=SESSION_SUMMARY_PROMPT if session_summary else CONSOLIDATION_PROMPT,
            payload=payload,
            output_schema=ConsolidationPlan,
            fallback_output=ConsolidationPlan(),
            metadata=metadata,
            timeout=timeout,
        )

    async def extract_tool_delta(
        self,
        *,
        session_content: str,
        context_state: MemoryContextState,
        timeout: float = 12.0,
    ) -> MemoryDelta:
        return await self._safe_ainvoke_structured(
            task_name=self._tool_delta_task,
            prompt=TOOL_DELTA_PROMPT,
            payload={"session_content": session_content},
            output_schema=MemoryDelta,
            fallback_output=MemoryDelta(),
            metadata=self.base_trace_metadata(
                context_state=context_state,
                operation="tool_delta",
                memory_type=MemoryType.TOOLS,
            ),
            timeout=timeout,
        )

    async def extract_env_delta(
        self,
        *,
        memory_input: EnvMemoryInput,
        context_state: MemoryContextState,
        previous_env_memory: str | None = None,
        conversation_context: str | None = None,
        timeout: float = 25.0,
    ) -> EnvMemoryDelta:
        if not self._env_delta_task:
            logger.debug("[Memory] env delta skipped because env_delta_task is not configured")
            return EnvMemoryDelta()

        if not memory_input.has_environment_evidence:
            return EnvMemoryDelta()

        model_input = self._build_env_model_input(
            memory_input=memory_input,
            previous_env_memory=previous_env_memory,
            conversation_context=conversation_context,
        )

        return await self._safe_ainvoke_structured(
            task_name=self._env_delta_task,
            prompt=ENV_DELTA_PROMPT,
            payload={"env_messages": model_input},
            output_schema=EnvMemoryDelta,
            fallback_output=EnvMemoryDelta(),
            metadata=self.base_trace_metadata(
                context_state=context_state,
                operation="env_delta",
                memory_type=MemoryType.ENV,
                extra={
                    "slice_count": len(memory_input.slices),
                    "media_count": len(memory_input.observations),
                },
            ),
            timeout=timeout,
            tracing_payload=False,
            raise_on_error=True,
        )
