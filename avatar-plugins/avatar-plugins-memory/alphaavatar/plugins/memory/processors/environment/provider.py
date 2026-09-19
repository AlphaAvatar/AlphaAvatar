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
from typing import Any
from uuid import uuid4

from alphaavatar.agents.providers import ProviderGateway
from alphaavatar.agents.providers.schema import (
    ModelInput,
    ModelInputMessage,
    ModelRole,
    ModelTextPart,
)

from ...log import logger
from ...schemas.patch import EnvMemoryDelta
from .config import EnvironmentProviderConfig
from .input_builder import EnvMemoryInput
from .prompt import ENV_DELTA_PROMPT


class EnvironmentProvider:
    def __init__(
        self,
        config: EnvironmentProviderConfig,
    ) -> None:
        if not config.task:
            raise ValueError("Environment provider task cannot be empty")

        self._task = config.task
        self._gateway = ProviderGateway(config.gateway)
        self._gateway.validate_tasks([self._task])

    @staticmethod
    def _model_input(
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
                    parts=(
                        ModelTextPart(instructions),
                        memory_input.temporal,
                    ),
                ),
            )
        )

    async def extract(
        self,
        *,
        memory_input: EnvMemoryInput,
        previous_env_memory: str | None,
        conversation_context: str | None,
        metadata: dict[str, Any],
        timeout: float,
    ) -> EnvMemoryDelta:
        if not memory_input.has_environment_evidence:
            return EnvMemoryDelta()

        try:
            result = await asyncio.wait_for(
                self._gateway.ainvoke_structured(
                    task_name=self._task,
                    prompt=ENV_DELTA_PROMPT,
                    payload={
                        "env_messages": self._model_input(
                            memory_input=memory_input,
                            previous_env_memory=previous_env_memory,
                            conversation_context=conversation_context,
                        )
                    },
                    output_schema=EnvMemoryDelta,
                    metadata=metadata,
                    tracing_payload=False,
                ),
                timeout=timeout,
            )

            return (
                result.output
                if isinstance(result.output, EnvMemoryDelta)
                else EnvMemoryDelta.model_validate(result.output)
            )

        except asyncio.CancelledError:
            raise

        except Exception:
            logger.exception(
                "[Memory] environment provider failed task=%s",
                self._task,
            )
            raise
