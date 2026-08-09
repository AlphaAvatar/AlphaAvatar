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

import base64
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from alphaavatar.agents.entrypoints.livekit.livekit_audio_codec import (
    from_livekit_audio_frame,
    to_livekit_audio_frame,
)
from alphaavatar.agents.entrypoints.livekit.livekit_video_codec import (
    from_livekit_video_frame,
    to_livekit_video_frame,
)
from alphaavatar.agents.providers.schema import (
    ModelAudioPart,
    ModelControlItem,
    ModelFunctionCall,
    ModelFunctionOutput,
    ModelImagePart,
    ModelInput,
    ModelInputMessage,
    ModelRole,
    ModelTextPart,
)
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.media import (
    AudioFrame,
    AudioSegmentPayload,
    ImagePayload,
    PayloadFormat,
    PayloadFormatUnavailable,
    PayloadView,
    VideoFrame,
)
from alphaavatar.core.time import RuntimeClock, RuntimeTime, RuntimeTimeRange
from livekit import rtc
from livekit.agents import llm


def _runtime_time(clock: RuntimeClock, unix_seconds: float | None) -> RuntimeTime:
    now = clock.now()
    return (
        now
        if unix_seconds is None or unix_seconds <= 0
        else now.shifted(unix_seconds - now.unix_seconds)
    )


def message_content(message: llm.ChatMessage) -> tuple[Any, ...]:
    content = message.content
    if content is None:
        return ()
    return (content,) if isinstance(content, str) else tuple(content)


def image_content_to_observation(
    content: llm.ImageContent,
    *,
    clock: RuntimeClock,
    message_id: str,
    content_index: int,
    at: RuntimeTime | None = None,
) -> EnvObservation:
    occurred_at = at or clock.now()
    metadata: dict[str, Any] = {
        "message_id": message_id,
        "content_id": content.id,
        "content_index": content_index,
        "input_origin": "direct_upload",
        "inference_width": content.inference_width,
        "inference_height": content.inference_height,
        "inference_detail": content.inference_detail,
    }
    payload = (
        ImagePayload.create(
            image_id=content.id,
            frame=from_livekit_video_frame(content.image),
            metadata=dict(metadata),
        )
        if isinstance(content.image, rtc.VideoFrame)
        else ImagePayload.create(
            image_id=content.id,
            uri=content.image,
            metadata=dict(metadata),
        )
    )
    return EnvObservation.image_input(
        time_range=RuntimeTimeRange.point(occurred_at),
        source_id=f"entrypoint:livekit:image:{message_id}:{content.id}",
        payload=payload,
        mime_type=content.mime_type or "image/*",
        metadata=metadata,
    )


def audio_content_to_observation(
    content: llm.AudioContent,
    *,
    clock: RuntimeClock,
    message_id: str,
    content_index: int,
    created_at: float | None = None,
    at: RuntimeTime | None = None,
) -> EnvObservation | None:
    frames = [from_livekit_audio_frame(frame) for frame in content.frame]
    if not frames:
        return None

    segment_id = f"chat:{message_id}:{content_index}"
    end = at or _runtime_time(clock, created_at)
    duration = sum(frame.duration_sec for frame in frames)
    metadata = {
        "message_id": message_id,
        "content_index": content_index,
        "segment_id": segment_id,
        "input_origin": "direct_upload",
    }
    payload = AudioSegmentPayload.from_frames(
        segment_id=segment_id,
        frames=frames,
        source_observation_ids=(),
        metadata=dict(metadata),
    )
    return EnvObservation.audio_segment(
        time_range=RuntimeTimeRange(start=end.shifted(-duration), end=end),
        source_id=f"entrypoint:livekit:audio:{message_id}",
        payload=payload,
        metadata=metadata,
    )


class LiveKitModelInput:
    def __init__(self, *, clock: RuntimeClock) -> None:
        self._clock = clock

    def from_chat_context(
        self,
        chat_ctx: llm.ChatContext,
        *,
        deferred_message_ids: set[str] | None = None,
    ) -> ModelInput:
        deferred = deferred_message_ids or set()
        items: list[Any] = []
        for item in chat_ctx.items:
            if isinstance(item, llm.ChatMessage):
                parts: list[Any] = []
                content_items = () if item.id in deferred else message_content(item)
                for index, content in enumerate(content_items):
                    if isinstance(content, str):
                        parts.append(ModelTextPart(content))
                    elif isinstance(content, llm.ImageContent):
                        parts.append(
                            ModelImagePart(
                                image_content_to_observation(
                                    content,
                                    clock=self._clock,
                                    message_id=item.id,
                                    content_index=index,
                                    at=_runtime_time(self._clock, item.created_at),
                                )
                            )
                        )
                    elif isinstance(content, llm.AudioContent):
                        observation = audio_content_to_observation(
                            content,
                            clock=self._clock,
                            message_id=item.id,
                            content_index=index,
                            created_at=item.created_at,
                        )
                        if observation is not None:
                            parts.append(ModelAudioPart(observation))
                items.append(
                    ModelInputMessage(
                        id=item.id,
                        role=ModelRole(item.role),
                        parts=tuple(parts),
                        interrupted=item.interrupted,
                        transcript_confidence=item.transcript_confidence,
                        created_at=item.created_at,
                        metadata=MappingProxyType(dict(item.extra or {})),
                    )
                )
            elif isinstance(item, llm.FunctionCall):
                items.append(
                    ModelFunctionCall(
                        id=item.id,
                        call_id=item.call_id,
                        name=item.name,
                        arguments=item.arguments,
                        created_at=item.created_at,
                        group_id=item.group_id,
                        metadata=MappingProxyType(dict(item.extra or {})),
                    )
                )
            elif isinstance(item, llm.FunctionCallOutput):
                items.append(
                    ModelFunctionOutput(
                        id=item.id,
                        call_id=item.call_id,
                        name=item.name,
                        output=item.output,
                        is_error=item.is_error,
                        created_at=item.created_at,
                    )
                )
            else:
                items.append(
                    ModelControlItem(
                        id=getattr(item, "id", uuid4().hex),
                        kind=str(getattr(item, "type", type(item).__name__)),
                        data=MappingProxyType(
                            item.model_dump() if hasattr(item, "model_dump") else {}
                        ),
                        created_at=getattr(item, "created_at", None),
                    )
                )
        return ModelInput(items=tuple(items))

    @staticmethod
    def _image_content(part: ModelImagePart) -> llm.ImageContent:
        observation = part.observation
        payload = observation.payload
        if payload is None:
            raise ValueError(f"Image observation has no payload: {observation.observation_id}")

        image: str | rtc.VideoFrame
        try:
            image = payload.get(
                PayloadFormat.IMAGE_URI, view=PayloadView.RAW, fallback_to_raw=False
            )
        except PayloadFormatUnavailable:
            try:
                frame = payload.get(
                    PayloadFormat.VIDEO_FRAME, view=PayloadView.ANNOTATED, fallback_to_raw=True
                )
            except PayloadFormatUnavailable:
                try:
                    encoded = payload.get(
                        PayloadFormat.IMAGE_JPEG_BYTES,
                        view=PayloadView.ANNOTATED,
                        fallback_to_raw=True,
                    )
                    mime_type = "image/jpeg"
                except PayloadFormatUnavailable:
                    encoded = payload.get(
                        PayloadFormat.IMAGE_PNG_BYTES,
                        view=PayloadView.ANNOTATED,
                        fallback_to_raw=True,
                    )
                    mime_type = "image/png"
                image = f"data:{mime_type};base64,{base64.b64encode(encoded).decode()}"
            else:
                if not isinstance(frame, VideoFrame):
                    raise TypeError(f"Unsupported image frame type: {type(frame).__name__}")
                image = to_livekit_video_frame(frame)

        metadata = observation.metadata
        return llm.ImageContent(
            image=image,
            inference_width=metadata.get("inference_width"),
            inference_height=metadata.get("inference_height"),
            inference_detail=metadata.get("inference_detail", "auto"),
            mime_type=observation.mime_type,
        )

    @staticmethod
    def _audio_content(part: ModelAudioPart) -> llm.AudioContent:
        observation = part.observation
        payload = observation.payload
        if payload is None:
            raise ValueError(f"Audio observation has no payload: {observation.observation_id}")
        try:
            frame = payload.get(
                PayloadFormat.AUDIO_FRAME, view=PayloadView.RAW, fallback_to_raw=False
            )
            frames = [to_livekit_audio_frame(frame)]
        except PayloadFormatUnavailable:
            data = payload.get(
                PayloadFormat.AUDIO_PCM16_BYTES, view=PayloadView.RAW, fallback_to_raw=False
            )
            frame = AudioFrame(
                sample_rate=payload.sample_rate,
                num_channels=payload.num_channels,
                samples_per_channel=payload.samples_per_channel,
                data=data,
            )
            frames = [to_livekit_audio_frame(frame)]
        return llm.AudioContent(frame=frames)

    def to_chat_context(self, model_input: ModelInput) -> llm.ChatContext:
        if model_input.realtime is not None:
            raise RuntimeError("Realtime ModelInput requires a native ModelProviderAdapter")

        items: list[Any] = []
        for item in model_input.items:
            if isinstance(item, ModelInputMessage):
                content: list[Any] = []
                for part in item.parts:
                    if isinstance(part, ModelTextPart):
                        content.append(part.text)
                    elif isinstance(part, ModelImagePart):
                        content.append(self._image_content(part))
                    elif isinstance(part, ModelAudioPart):
                        content.append(self._audio_content(part))
                items.append(
                    llm.ChatMessage(
                        id=item.id,
                        role=item.role.value,
                        content=content,
                        interrupted=item.interrupted,
                        transcript_confidence=item.transcript_confidence,
                        created_at=item.created_at or 0.0,
                        extra=dict(item.metadata),
                    )
                )
            elif isinstance(item, ModelFunctionCall):
                items.append(
                    llm.FunctionCall(
                        id=item.id,
                        call_id=item.call_id,
                        name=item.name,
                        arguments=item.arguments,
                        created_at=item.created_at or 0.0,
                        group_id=item.group_id,
                        extra=dict(item.metadata),
                    )
                )
            elif isinstance(item, ModelFunctionOutput):
                items.append(
                    llm.FunctionCallOutput(
                        id=item.id,
                        call_id=item.call_id,
                        name=item.name,
                        output=item.output,
                        is_error=item.is_error,
                        created_at=item.created_at or 0.0,
                    )
                )
            elif isinstance(item, ModelControlItem):
                if item.kind == "agent_handoff":
                    items.append(
                        llm.AgentHandoff(
                            id=item.id,
                            old_agent_id=item.data.get("old_agent_id"),
                            new_agent_id=str(item.data["new_agent_id"]),
                            created_at=item.created_at or 0.0,
                        )
                    )
                elif item.kind == "agent_config_update":
                    items.append(
                        llm.AgentConfigUpdate(
                            id=item.id,
                            instructions=item.data.get("instructions"),
                            tools_added=item.data.get("tools_added"),
                            tools_removed=item.data.get("tools_removed"),
                            created_at=item.created_at or 0.0,
                        )
                    )

        return llm.ChatContext(items=items)
