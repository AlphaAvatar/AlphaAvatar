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
from collections.abc import AsyncIterator

from alphaavatar.core.env import (
    PerceptionSegmentRef,
    PerceptionSourceRef,
)
from alphaavatar.core.media import AudioFrame

from ..schema import InvocationDetection


class InvocationDetectorStreamBase(ABC):
    def __aiter__(self) -> AsyncIterator[InvocationDetection]:
        return self

    @abstractmethod
    async def __anext__(self) -> InvocationDetection:
        raise StopAsyncIteration

    @abstractmethod
    def push_frame(
        self,
        frame: AudioFrame,
        *,
        segment: PerceptionSegmentRef,
        observation_id: str,
    ) -> bool:
        """Submit one frame without blocking."""

    @abstractmethod
    def finish_segment(
        self,
        segment: PerceptionSegmentRef,
    ) -> bool:
        """Flush and close one speech segment without blocking."""

    @property
    @abstractmethod
    def dropped_chunks(self) -> int:
        raise NotImplementedError

    @abstractmethod
    async def aclose(self) -> None:
        raise NotImplementedError


class InvocationDetectorBase(ABC):
    @property
    @abstractmethod
    def provider(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def model(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def stream(
        self,
        *,
        source: PerceptionSourceRef,
    ) -> InvocationDetectorStreamBase:
        raise NotImplementedError

    @abstractmethod
    async def aclose(self) -> None:
        raise NotImplementedError
