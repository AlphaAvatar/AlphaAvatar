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
import asyncio
import base64
import hashlib
import json
from typing import Any, TypeVar

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from alphaavatar.agents.memory import MemoryCache, MemoryType
from alphaavatar.agents.providers import ProviderGateway, ProvidersConfig
from alphaavatar.core.env import EnvObservation

from .log import logger
from .memory_op import EnvMemoryDelta, MemoryDelta
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

    This class owns all provider invocation logic for memory extraction:
    - conversation delta
    - tool delta
    - environment delta

    MemoryRuntime decides when to call it.
    This class decides how to call the provider task safely.
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

    def _stable_digest(self, value: Any) -> str:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
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

    def _env_trace_metadata(
        self,
        *,
        memory_cache: MemoryCache,
        observations: list[EnvObservation],
    ) -> dict[str, Any]:
        observation_signature = [
            {
                "id": obs.observation_id,
                "kind": obs.kind,
                "timestamp": obs.timestamp,
                "source_id": obs.source_id,
                "frame_id": obs.frame_id,
                "has_payload": obs.has_payload,
                "has_path": obs.has_persisted_evidence,
                "annotation_count": len(getattr(obs, "annotations", []) or []),
            }
            for obs in observations
        ]

        return self._base_trace_metadata(
            memory_cache=memory_cache,
            operation="env_delta",
            memory_type=MemoryType.ENV,
            component="env_memory_delta_extractor",
            extra={
                "observation_count": len(observations),
                "payload_count": sum(1 for obs in observations if obs.has_payload),
                "persisted_evidence_count": sum(
                    1 for obs in observations if obs.has_persisted_evidence
                ),
                "observation_kinds": sorted({obs.kind for obs in observations}),
                "source_count": len({obs.source_id for obs in observations if obs.source_id}),
                "observation_digest": self._stable_digest(observation_signature),
            },
        )

    def _content_block_type_for_observation(self, observation: EnvObservation) -> str:
        if observation.kind in {"video_frame", "screen_frame"}:
            return "image"

        if observation.kind == "video_clip":
            return "video"

        if observation.kind == "audio_segment":
            return "audio"

        return "file"

    def _observation_to_content_block(
        self,
        observation: EnvObservation,
    ) -> dict[str, Any] | None:
        """
        Convert EnvObservation.model_payload into a LangChain multimodal content block.

        Rules:
        - Use observation.model_payload, which may be a rendered/model-facing payload.
        - Do not convert runtime-only objects such as LiveKit rtc.VideoFrame here.
        - RTC adapters or annotation renderers should provide bytes/provider-ready blocks.
        """

        payload = observation.model_payload
        if payload is None:
            return None

        if isinstance(payload, dict):
            return payload

        block_type = self._content_block_type_for_observation(observation)
        mime_type = observation.model_mime_type

        if isinstance(payload, bytes):
            encoded = base64.b64encode(payload).decode("utf-8")

            return {
                "type": block_type,
                "base64": encoded,
                "mime_type": mime_type or self._default_mime_type_for_block(block_type),
            }

        if isinstance(payload, str):
            payload_kind = observation.metadata.get("payload_kind")

            if payload_kind == "url":
                return {
                    "type": block_type,
                    "url": payload,
                }

            if payload_kind == "file_id":
                return {
                    "type": block_type,
                    "file_id": payload,
                    "mime_type": mime_type or self._default_mime_type_for_block(block_type),
                }

            # Default: treat string payload as base64 inline content.
            return {
                "type": block_type,
                "base64": payload,
                "mime_type": mime_type or self._default_mime_type_for_block(block_type),
            }

        logger.warning(
            "[Memory] unsupported env observation model payload type: "
            "observation_id=%s kind=%s payload_type=%s. "
            "Expected dict, bytes, base64 string, url, or file_id. "
            "Runtime-only payloads such as rtc.VideoFrame should be converted by "
            "RTC adapters or annotation renderers before env extraction.",
            observation.observation_id,
            observation.kind,
            type(payload).__name__,
        )
        return None

    def _default_mime_type_for_block(self, block_type: str) -> str:
        if block_type == "image":
            return "image/jpeg"
        if block_type == "video":
            return "video/mp4"
        if block_type == "audio":
            return "audio/wav"
        return "application/octet-stream"

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

        for obs in observations:
            block = self._observation_to_content_block(obs)
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
            logger.warning("[Memory] extraction timeout task=%s", task_name)
            return fallback_output
        except Exception:
            logger.exception("[Memory] extraction failed task=%s", task_name)
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
        timeout: float = 20.0,
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
            metadata=self._env_trace_metadata(
                memory_cache=memory_cache,
                observations=observations,
            ),
            timeout=timeout,
            tracing_payload=False,
        )
