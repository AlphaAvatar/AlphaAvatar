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

from livekit.agents import llm

from alphaavatar.agents.avatar.vision.base import VisionBase
from alphaavatar.agents.log import logger


class RealtimeVision(VisionBase):
    """Realtime model visual input strategy.

    Reserved for realtime multimodal models.

    Unlike SampledFrameVision, this strategy should not inject ImageContent into
    ChatContext manually. It should configure the LiveKit room/model pipeline so
    the realtime model can receive video input directly.
    """

    def start(self) -> None:
        logger.info("RealtimeVision is not implemented yet")

    async def stop(self) -> None:
        return

    def inject_into_chat_ctx(self, chat_ctx: llm.ChatContext) -> None:
        return
