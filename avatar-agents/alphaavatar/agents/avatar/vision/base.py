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

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from livekit.agents import llm

if TYPE_CHECKING:
    from alphaavatar.agents.avatar.engine import AvatarEngine


class VisionBase(ABC):
    """Base class for AlphaAvatar visual input strategies."""

    def __init__(self, agent: AvatarEngine) -> None:
        self.agent = agent

    @abstractmethod
    def start(self) -> None:
        """Start visual input processing."""
        raise NotImplementedError

    @abstractmethod
    async def stop(self) -> None:
        """Stop visual input processing and cleanup resources."""
        raise NotImplementedError

    def inject_into_chat_ctx(self, chat_ctx: llm.ChatContext) -> None:
        """Inject visual content into the chat context before LLM inference.

        Default implementation does nothing.
        """
        return


class NoopVision(VisionBase):
    """No-op visual input strategy."""

    def start(self) -> None:
        return

    async def stop(self) -> None:
        return
