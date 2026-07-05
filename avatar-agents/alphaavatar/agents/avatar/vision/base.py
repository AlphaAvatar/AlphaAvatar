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

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from livekit.agents import llm

from alphaavatar.agents.log import logger
from alphaavatar.agents.plugin import AvatarRuntimePlugin
from alphaavatar.core.env import EnvObservation

if TYPE_CHECKING:
    from alphaavatar.agents.avatar.engine import AvatarEngine


@dataclass(slots=True)
class _VisualFrameSnapshot:
    """
    A bounded local snapshot for Avatar Vision.

    Important:
    - `payload` keeps the original runtime frame, usually rtc.VideoFrame.
    - `observation` keeps a reference to the shared EnvObservation so late
      annotations/rendered_payload can still be picked up at injection time.
    """

    payload: Any = field(repr=False, compare=False)
    timestamp: str
    observation_id: str

    observation: EnvObservation | None = field(default=None, repr=False, compare=False)

    frame_id: str | None = None
    source_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class VisionBase(AvatarRuntimePlugin):
    """Base class for AlphaAvatar visual input strategies."""

    def __init__(self, agent: AvatarEngine, vision_id: str) -> None:
        self.agent = agent
        self.vision_id = vision_id

        vision_config = self.agent.avatar_config.vision

        self._video_frame_buffer: deque[_VisualFrameSnapshot] = deque(
            maxlen=vision_config.sampling.frame_buffer_size
        )
        self._last_video_frame_sample_ts: float | None = None
        self._started: bool = False

    def inject_into_chat_ctx(self, chat_ctx: llm.ChatContext) -> None:
        """Inject visual content into the chat context before LLM inference.

        Default implementation does nothing.
        """
        ...

    """Runtime Op"""

    async def on_session_start(self, **kwargs) -> None:
        """Start visual input processing."""
        vision_config = self.agent.avatar_config.vision

        self._started = True

        logger.info(
            "AvatarVision started with perception bus vision_id=%s mode=%s",
            self.vision_id,
            vision_config.input.mode,
        )

    async def on_session_stop(self, **kwargs) -> None:
        """Stop visual input processing and cleanup resources."""
        self._started = False
        self._video_frame_buffer.clear()
        self._last_video_frame_sample_ts = None


class NoopVision(VisionBase):
    """No-op visual input strategy."""

    CONSUMER_ID = "avatar.vision.noop"

    def __init__(self, agent) -> None:
        super().__init__(agent, vision_id=self.CONSUMER_ID)
