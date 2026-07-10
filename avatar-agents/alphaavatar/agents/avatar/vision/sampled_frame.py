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
from contextlib import suppress
from datetime import datetime
from typing import Any

from livekit import rtc
from livekit.agents import llm

from alphaavatar.agents.avatar.perception import (
    to_livekit_video_frame,
)
from alphaavatar.agents.avatar.vision.base import VisionBase, _VisualFrameSnapshot
from alphaavatar.agents.configs.plugins.vision_config import VisionInputMode
from alphaavatar.agents.constants import VIDEO_VISION_INTERVAL_SEC
from alphaavatar.agents.log import debug_every, logger
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.media import (
    PayloadFormat,
    PayloadFormatUnavailable,
    PayloadView,
    VideoFrame,
)

from .constants import (
    LATEST_VIDEO_FRAME_LABEL,
    VIDEO_FRAME_LABEL_PREFIX,
    VISUAL_INPUT_PREFIX,
)

VISION_BUS_POLL_INTERVAL_SEC = 0.05


class SampledFrameVision(VisionBase):
    """Sampled-frame visual input from the shared PerceptionBus.

    This strategy:
    1. asynchronously reads pending video observations from SessionRuntime.perception_bus,
    2. samples them into a bounded local buffer,
    3. injects selected frames into the latest user message before LLM inference.

    It does not subscribe to LiveKit tracks directly.
    VideoInputRuntime / RTC adapters are responsible for publishing FrameEvent
    into the shared PerceptionBus.
    """

    CONSUMER_ID = "avatar.vision.sampled_frame"

    def __init__(self, agent) -> None:
        super().__init__(agent, vision_id=self.CONSUMER_ID)
        self._pull_task: asyncio.Task[None] | None = None

    """Helper Op"""

    def _timestamp_to_seconds(self, value: str | None) -> float | None:
        if not value:
            return None

        try:
            return float(value)
        except (TypeError, ValueError):
            pass

        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except Exception:
            return None

    def _should_sample_observation(self, observation: EnvObservation) -> bool:
        ts = self._timestamp_to_seconds(observation.timestamp)

        # If timestamp cannot be parsed, do not drop the frame. The upstream
        # VideoInputRuntime may already have sampled frames.
        if ts is None:
            return True

        if (
            self._last_video_frame_sample_ts is not None
            and ts - self._last_video_frame_sample_ts < VIDEO_VISION_INTERVAL_SEC
        ):
            return False

        self._last_video_frame_sample_ts = ts
        return True

    def _observation_to_snapshot(
        self,
        observation: EnvObservation,
    ) -> _VisualFrameSnapshot | None:
        if observation.kind not in {
            "video_frame",
            "screen_frame",
        }:
            return None

        payload = observation.payload
        if payload is None:
            return None

        if not payload.has(
            PayloadFormat.VIDEO_FRAME,
            view=PayloadView.RAW,
            fallback_to_raw=False,
        ):
            return None

        if not self._should_sample_observation(observation):
            return None

        return _VisualFrameSnapshot(
            timestamp=observation.timestamp,
            observation_id=observation.observation_id,
            observation=observation,
            frame_id=observation.frame_id,
            source_id=observation.source_id,
            metadata=dict(observation.metadata or {}),
        )

    def _pull_pending_visual_frames(self) -> None:
        vision_config = self.agent.avatar_config.vision

        if not vision_config.use_sampled_frame_input:
            return

        # Small delay gives asynchronous face inference a chance to publish
        # an annotated representation before this frame enters the vision buffer.
        window = self.agent.perception_runtime.take_pending_observations(
            consumer_id=self.CONSUMER_ID,
            streams={"video", "screen"},
            require_payload=True,
            min_age_sec=0.25,
        )

        observations = window.observations

        if not observations:
            self.agent.perception_runtime.commit_observations(window)
            return

        accepted_count = 0

        for observation in observations:
            snapshot = self._observation_to_snapshot(observation)

            if snapshot is None:
                continue

            self._video_frame_buffer.append(snapshot)
            accepted_count += 1

        self.agent.perception_runtime.commit_observations(window)

        if accepted_count:
            debug_every(
                "Pulled visual frames accepted=%s pending=%s buffer=%s",
                accepted_count,
                len(observations),
                len(self._video_frame_buffer),
                key=(f"vision:sampled_frames_pulled:{self.agent.session_runtime.session_id}"),
                interval_sec=10.0,
            )

    def _select_visual_frames_for_turn(self) -> list[_VisualFrameSnapshot]:
        vision_config = self.agent.avatar_config.vision

        if not vision_config.use_sampled_frame_input:
            return []

        # Do not pull from PerceptionBus here.
        # Background _visual_observation_loop keeps _video_frame_buffer fresh.
        if not self._video_frame_buffer:
            return []

        if vision_config.input.mode == VisionInputMode.LATEST_FRAME_PER_TURN:
            return [self._video_frame_buffer[-1]]

        if vision_config.input.mode == VisionInputMode.SAMPLED_FRAMES_PER_TURN:
            frame_count = min(
                vision_config.sampling.frames_per_turn,
                len(self._video_frame_buffer),
            )
            return list(self._video_frame_buffer)[-frame_count:]

        return []

    def _resolve_livekit_frames(
        self,
        snapshots: list[_VisualFrameSnapshot],
    ) -> list[
        tuple[
            _VisualFrameSnapshot,
            rtc.VideoFrame,
        ]
    ]:
        resolved: list[
            tuple[
                _VisualFrameSnapshot,
                rtc.VideoFrame,
            ]
        ] = []

        for snapshot in snapshots:
            payload = snapshot.observation.payload
            if payload is None:
                continue

            try:
                frame = payload.get(
                    PayloadFormat.VIDEO_FRAME,
                    view=PayloadView.ANNOTATED,
                    fallback_to_raw=True,
                )
            except PayloadFormatUnavailable:
                continue

            if not isinstance(frame, VideoFrame):
                logger.warning(
                    "Skip visual frame because VIDEO_FRAME representation "
                    "is not VideoFrame observation_id=%s type=%s",
                    snapshot.observation_id,
                    type(frame).__name__,
                )
                continue

            try:
                livekit_frame = to_livekit_video_frame(frame)
            except Exception:
                logger.exception(
                    "Failed to convert visual frame to LiveKit frame observation_id=%s",
                    snapshot.observation_id,
                )
                continue

            resolved.append(
                (
                    snapshot,
                    livekit_frame,
                )
            )

        return resolved

    def _build_visual_instruction(self, frame_count: int) -> str:
        if frame_count == 1:
            frame_desc = "One sampled moment"
            visual_scope = "the video"
        else:
            frame_desc = f"{frame_count} sampled moments, ordered from earliest to latest,"
            visual_scope = "the video sequence"

        return (
            f"\n{VISUAL_INPUT_PREFIX}\n"
            f"{frame_desc} from the user's live video stream are available for this user message. "
            "Always answer the user's text message normally. "
            "Use the live video context only when the user's message explicitly refers to the video, camera, screen, scene, visible object, gesture, appearance, action, or something currently shown, "
            "or when the user's question clearly depends on what is visible. "
            "If the user's message does not require visual grounding, ignore the live video context and respond as a normal conversation. "
            f"When visual grounding is needed, rely only on what is visible in {visual_scope} and avoid guessing beyond what is shown. "
            "When responding naturally to the user, prefer phrasing such as "
            "'from your video', 'based on your video', or 'from what I can see in the video', "
            "and avoid phrasing such as 'from the attached frames', 'in the attached frames', 'from the image', or 'from the picture' "
            "unless the user explicitly asks about frames or images."
        )

    def _message_has_visual_input(self, message: llm.ChatMessage) -> bool:
        content = getattr(message, "content", None)

        if not isinstance(content, list):
            return False

        for part in content:
            if isinstance(part, str):
                stripped = part.strip()
                if VISUAL_INPUT_PREFIX in stripped:
                    return True
                if stripped.startswith(VIDEO_FRAME_LABEL_PREFIX):
                    return True
                if stripped == LATEST_VIDEO_FRAME_LABEL:
                    return True

            if getattr(part, "type", None) == "image_content":
                return True

            if part.__class__.__name__ == "ImageContent":
                return True

        return False

    async def _visual_observation_loop(self) -> None:
        while True:
            try:
                self._pull_pending_visual_frames()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("AvatarVision failed to pull visual frames from perception bus")

            await asyncio.sleep(VISION_BUS_POLL_INTERVAL_SEC)

    """Base Op"""

    def inject_into_chat_ctx(self, chat_ctx: llm.ChatContext) -> None:
        vision_config = self.agent.avatar_config.vision
        snapshots = self._select_visual_frames_for_turn()

        if not snapshots:
            return

        latest_user_message: llm.ChatMessage | None = None

        for item in reversed(chat_ctx.items):
            if isinstance(item, llm.ChatMessage) and item.role == "user":
                latest_user_message = item
                break

        if latest_user_message is None:
            logger.warning("No latest user message found; skip visual frame injection")
            return

        # Normalize original user content while preserving its original order.
        if latest_user_message.content is None:
            original_content = []
        elif isinstance(latest_user_message.content, list):
            original_content = list(latest_user_message.content)
        else:
            original_content = [latest_user_message.content]

        # Avoid duplicate visual injection.
        latest_user_message.content = original_content
        if self._message_has_visual_input(latest_user_message):
            logger.debug("Latest user message already has visual input; skip duplicate injection")
            return

        resolved_frames = self._resolve_livekit_frames(snapshots)

        if not resolved_frames:
            return

        frame_count = len(resolved_frames)

        visual_content: list[Any] = [self._build_visual_instruction(frame_count)]

        for index, (_, livekit_frame) in enumerate(
            resolved_frames,
            start=1,
        ):
            if frame_count > 1:
                visual_content.append(
                    f"{VIDEO_FRAME_LABEL_PREFIX}{index}/{frame_count} — chronological order]"
                )
            else:
                visual_content.append(LATEST_VIDEO_FRAME_LABEL)

            visual_content.append(
                llm.ImageContent(
                    image=livekit_frame,
                    inference_width=vision_config.inference.width,
                    inference_height=vision_config.inference.height,
                )
            )

        # Put visual input before the user's text/message content.
        latest_user_message.content = [
            *visual_content,
            *original_content,
        ]

        logger.info(
            "Injected visual frames into latest user message frame_count=%s mode=%s",
            frame_count,
            vision_config.input.mode,
        )

        if vision_config.clear_after_turn:
            self._video_frame_buffer.clear()

    """Runtime Op"""

    async def on_session_start(self) -> None:
        await super().on_session_start()

        vision_config = self.agent.avatar_config.vision

        if not vision_config.use_sampled_frame_input:
            return

        if self._pull_task is not None and not self._pull_task.done():
            return

        self._pull_task = asyncio.create_task(
            self._visual_observation_loop(),
            name="avatar_vision_observation_loop",
        )

        logger.info(
            "AvatarVision observation loop started consumer_id=%s interval=%ss sample_interval=%ss",
            self.CONSUMER_ID,
            VISION_BUS_POLL_INTERVAL_SEC,
            VIDEO_VISION_INTERVAL_SEC,
        )

    async def on_session_stop(self) -> None:
        if self._pull_task is not None:
            self._pull_task.cancel()

            with suppress(asyncio.CancelledError):
                await self._pull_task

            self._pull_task = None

        await super().on_session_stop()
