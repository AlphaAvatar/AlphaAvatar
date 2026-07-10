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
import base64
import hashlib
import json
from typing import Any, TypeVar

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from alphaavatar.agents.memory import (
    MemoryCache,
    MemoryType,
)
from alphaavatar.agents.providers import (
    ProviderGateway,
    ProvidersConfig,
)
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.media import (
    PayloadFormat,
    PayloadFormatUnavailable,
    PayloadView,
)

from .log import logger
from .memory_op import (
    EnvMemoryDelta,
    MemoryDelta,
)
from .memory_prompts import (
    CONVERSATION_DELTA_PROMPT,
    ENV_DELTA_PROMPT,
    TOOL_DELTA_PROMPT,
)

TStructuredOutput = TypeVar("TStructuredOutput", bound=BaseModel)


class MemoryProviderConfig(BaseModel):
    conversation_delta_task: str = "memory.conversation_delta"
    tool_delta_task: str = "memory.tool_delta"

    # Optional. Some deployments do not need online ENV memory extraction.
    # If None or empty, extract_env_delta() returns an empty EnvMemoryDelta.
    # If set, e.g, `memory.env_delta`, this task is invoked for ENV memory extraction.
    env_delta_task: str | None = None

    gateway: ProvidersConfig = Field(default_factory=ProvidersConfig)


class MemoryDeltaExtractor:
    """
    Provider-backed memory delta extractor.

    Runtime media conversion is not performed here.

    The input adapter and annotation renderers are responsible for adding
    model-usable representations to MediaPayload. This extractor only selects
    the representation required by the ENV memory provider.
    """

    def __init__(self, config: MemoryProviderConfig | None = None) -> None:
        self._config = config or MemoryProviderConfig()

        self._conversation_delta_task = self._config.conversation_delta_task
        self._tool_delta_task = self._config.tool_delta_task
        self._env_delta_task = self._config.env_delta_task

        tasks_to_validate = [
            task
            for task in [
                self._conversation_delta_task,
                self._tool_delta_task,
                self._env_delta_task,
            ]
            if task
        ]

        self._provider_gateway = ProviderGateway(self._config.gateway)
        self._provider_gateway.validate_tasks(tasks_to_validate)

    @property
    def config(self) -> MemoryProviderConfig:
        return self._config

    """Helper Op"""

    def _stable_digest(
        self,
        value: Any,
    ) -> str:
        try:
            text = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
        except Exception:
            text = str(value)

        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def _base_trace_metadata(
        self,
        *,
        memory_cache: MemoryCache,
        operation: str,
        memory_type: MemoryType,
        component: str = "memory_delta_extractor",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "provider_dir": str(memory_cache.provider_dir),
            "plugin": "memory",
            "component": component,
            "operation": operation,
            "session_id": memory_cache.session_id,
            "cache_type": str(memory_cache.cache_type),
            "memory_type": memory_type.value,
        }

        if extra:
            metadata.update(extra)

        return metadata

    def _observation_has_annotated_image(
        self,
        observation: EnvObservation,
    ) -> bool:
        payload = observation.payload

        if payload is None:
            return False

        return payload.has(
            PayloadFormat.IMAGE_JPEG_BYTES,
            view=PayloadView.ANNOTATED,
            fallback_to_raw=False,
        )

    def _observation_to_content_block(
        self,
        observation: EnvObservation,
    ) -> dict[str, Any] | None:
        """
        Convert an AlphaAvatar EnvObservation into a LangChain multimodal block.

        Selection policy:

        1. Use an explicitly prepared generic provider content block when
           available.
        2. For video_frame/screen_frame, prefer annotated JPEG.
        3. Fall back to raw JPEG when no annotated representation exists.

        No LiveKit or RTC conversion is allowed here.
        """

        payload = observation.payload

        if payload is None:
            return None

        # Allows future media/provider adapters to publish an already prepared
        # provider-neutral block without changing MemoryDeltaExtractor.
        try:
            provider_block = payload.get(
                PayloadFormat.PROVIDER_CONTENT_BLOCK,
                view=PayloadView.ANNOTATED,
                fallback_to_raw=True,
            )
        except PayloadFormatUnavailable:
            provider_block = None

        if provider_block is not None:
            if isinstance(
                provider_block,
                dict,
            ):
                return provider_block

            logger.warning(
                "[Memory] invalid provider content block. observation_id=%s type=%s",
                observation.observation_id,
                type(provider_block).__name__,
            )
            return None

        if observation.kind not in {
            "video_frame",
            "screen_frame",
        }:
            logger.warning(
                "[Memory] ENV observation modality is not yet supported. observation_id=%s kind=%s",
                observation.observation_id,
                observation.kind,
            )
            return None

        try:
            image_bytes = payload.get(
                PayloadFormat.IMAGE_JPEG_BYTES,
                view=PayloadView.ANNOTATED,
                fallback_to_raw=True,
            )
        except PayloadFormatUnavailable:
            logger.warning(
                "[Memory] JPEG representation unavailable. observation_id=%s kind=%s frame_id=%s",
                observation.observation_id,
                observation.kind,
                observation.frame_id,
            )
            return None

        if not isinstance(
            image_bytes,
            bytes,
        ):
            logger.warning(
                "[Memory] invalid JPEG representation type. observation_id=%s kind=%s type=%s",
                observation.observation_id,
                observation.kind,
                type(image_bytes).__name__,
            )
            return None

        encoded = base64.b64encode(image_bytes).decode("utf-8")

        return {
            "type": "image",
            "base64": encoded,
            "mime_type": "image/jpeg",
        }

    def _build_env_delta_payload(
        self,
        *,
        observations: list[EnvObservation],
        previous_env_memory: str | None,
        conversation_context: str | None,
    ) -> dict[str, Any]:
        content: list[dict[str, Any]] = []

        header_parts = [
            "Generate environment memory delta from the following ordered multimodal observation stream.",
            "",
            "Output only `EnvMemoryDelta`.",
            "",
            "### OUTPUT SCHEMA MEANING",
            "- `env_memory_entries` are environment memories for MemoryType.ENV.",
            "- Do not output `assistant_memory_entries`.",
            "- Do not output `user_or_tool_memory_entries`.",
            "",
            "### PREVIOUS ENV MEMORY",
            "```text",
            previous_env_memory or "",
            "```",
            "",
            "### CONVERSATION CONTEXT IN THIS OBSERVATION WINDOW",
            "```text",
            conversation_context or "",
            "```",
            "",
            "The multimodal stream starts immediately after this text.",
            "",
            "Use the image/video/audio blocks as the primary evidence.",
            "Extract only useful environment memories for future recall, grounding, personalization, or visual-history QA.",
            "Prefer concrete episodic observations: visible people, actions, object changes, locations, screen/room state, and repeated environmental patterns.",
            "Do not invent identities from visual appearance, face_id, speaker_id, voice_id, or local object ids.",
            "If identity is unknown, use neutral labels such as unknown person, visible person, speaker, object, screen, or room.",
            "Do not describe every frame. Store only stable or meaningful observations.",
            "If the stream contains no useful new environment memory, return an empty `EnvMemoryDelta`.",
        ]

        content.append(
            {
                "type": "text",
                "text": "\n".join(header_parts),
            }
        )

        attached_count = 0

        for observation in observations:
            block = self._observation_to_content_block(observation)

            if block is None:
                continue

            content.append(block)
            attached_count += 1

        if attached_count == 0:
            logger.warning(
                "[Memory] env delta payload has no multimodal content blocks. observation_count=%s",
                len(observations),
            )

        return {
            "env_messages": [
                HumanMessage(content=content),
            ]
        }

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

            if isinstance(result.output, output_schema):
                return result.output

            return output_schema.model_validate(result.output)

        except asyncio.TimeoutError:
            logger.warning(
                "[Memory] extraction timeout task=%s timeout=%s",
                task_name,
                timeout,
            )
            return fallback_output

        except Exception as error:
            logger.exception(
                "[Memory] extraction failed task=%s error=%s",
                task_name,
                str(error),
            )
            return fallback_output

    """Delta Op"""

    async def extract_conversation_delta(
        self,
        *,
        session_content: str,
        memory_cache: MemoryCache,
        timeout: float = 12.0,
    ) -> MemoryDelta:
        payload = {
            "type": MemoryType.CONVERSATION.value,
            "session_content": session_content,
        }

        return await self._safe_ainvoke_structured(
            task_name=self._conversation_delta_task,
            prompt=CONVERSATION_DELTA_PROMPT,
            payload=payload,
            output_schema=MemoryDelta,
            fallback_output=MemoryDelta(),
            metadata=self._base_trace_metadata(
                memory_cache=memory_cache,
                operation="conversation_delta",
                memory_type=MemoryType.CONVERSATION,
            ),
            timeout=timeout,
        )

    async def extract_tool_delta(
        self,
        *,
        session_content: str,
        memory_cache: MemoryCache,
        timeout: float = 12.0,
    ) -> MemoryDelta:
        payload = {
            "type": MemoryType.TOOLS.value,
            "session_content": session_content,
        }

        return await self._safe_ainvoke_structured(
            task_name=self._tool_delta_task,
            prompt=TOOL_DELTA_PROMPT,
            payload=payload,
            output_schema=MemoryDelta,
            fallback_output=MemoryDelta(),
            metadata=self._base_trace_metadata(
                memory_cache=memory_cache,
                operation="tool_delta",
                memory_type=MemoryType.TOOLS,
            ),
            timeout=timeout,
        )

    async def extract_env_delta(
        self,
        *,
        observations: list[EnvObservation],
        memory_cache: MemoryCache,
        previous_env_memory: str | None = None,
        conversation_context: str | None = None,
        timeout: float = 25.0,
    ) -> EnvMemoryDelta:
        if not self._env_delta_task:
            logger.debug("[Memory] env delta skipped because env_delta_task is not configured.")
            return EnvMemoryDelta()

        if not observations:
            return EnvMemoryDelta()

        payload = self._build_env_delta_payload(
            observations=observations,
            previous_env_memory=previous_env_memory,
            conversation_context=conversation_context,
        )

        return await self._safe_ainvoke_structured(
            task_name=self._env_delta_task,
            prompt=ENV_DELTA_PROMPT,
            payload=payload,
            output_schema=EnvMemoryDelta,
            fallback_output=EnvMemoryDelta(),
            metadata=self._base_trace_metadata(
                memory_cache=memory_cache,
                operation="env_delta",
                memory_type=MemoryType.ENV,
            ),
            timeout=timeout,
            tracing_payload=False,
        )
