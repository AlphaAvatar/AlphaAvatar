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
from types import TracebackType

from alphaavatar.core.media import AudioFrame

from .schema.voice_activity import VoiceActivityEvent


class VADBase(ABC):
    """
    Factory owning reusable VAD model resources.

    Every stream() call creates independent recurrent and activity state.
    """

    @property
    @abstractmethod
    def model(self) -> str: ...

    @property
    @abstractmethod
    def provider(self) -> str: ...

    @property
    @abstractmethod
    def sample_rate(self) -> int: ...

    @property
    @abstractmethod
    def update_interval(self) -> float: ...

    @abstractmethod
    def stream(self) -> VADStreamBase:
        """Create one stateful detector stream."""

    async def aclose(self) -> None:
        """Release shared factory resources; consumers close their own streams."""
        return None


class VADStreamBase(ABC):
    """
    Stateful streaming VAD instance for one ordered audio source.

    push_frame(), flush(), and end_input() must be non-blocking. Heavy model
    inference should run in the stream's asynchronous worker.
    """

    @abstractmethod
    def push_frame(self, frame: AudioFrame) -> bool:
        """
        Queue one audio frame.

        Returns False when the stream cannot accept the frame. Router must
        treat that as an observable audio continuity gap.
        """

    @abstractmethod
    def flush(self) -> bool:
        """Reset detector state without closing the stream."""

    @abstractmethod
    def end_input(self) -> bool:
        """Signal that no more input frames will arrive."""

    @abstractmethod
    def __aiter__(self) -> AsyncIterator[VoiceActivityEvent]:
        """Iterate over normalized VAD events."""

    @abstractmethod
    async def aclose(self) -> None:
        """Close the stream and release its asynchronous resources."""

    async def __aenter__(self) -> VADStreamBase:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()
