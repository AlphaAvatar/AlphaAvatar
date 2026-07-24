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
from dataclasses import dataclass
from enum import StrEnum
from types import TracebackType

from alphaavatar.core.media import AudioFrame

from .schema.transcription import TranscriptionEvent


class STTInputMode(StrEnum):
    """How audio is sent to the STT provider."""

    REALTIME = "realtime"
    SEGMENT = "segment"


@dataclass(slots=True, frozen=True)
class STTCapabilities:
    input_mode: STTInputMode
    emits_interim_transcripts: bool
    persistent_connection: bool


class STTBase(ABC):
    """Factory owning reusable STT provider resources."""

    @property
    @abstractmethod
    def provider(self) -> str: ...

    @property
    @abstractmethod
    def model(self) -> str: ...

    @property
    @abstractmethod
    def capabilities(self) -> STTCapabilities: ...

    @property
    def streaming(self) -> bool:
        """
        Compatibility property.

        Prefer capabilities.input_mode in new code.
        """
        return self.capabilities.input_mode == STTInputMode.REALTIME

    @abstractmethod
    def stream(self, *, source_id: str) -> STTStreamBase:
        """Create one stateful transcription stream for an audio source."""


class STTStreamBase(ABC):
    """
    Stateful transcription stream for one ordered audio source.

    The implementation may either:

    - forward frames continuously to a realtime provider; or
    - buffer frames locally and submit completed segments.

    All input methods must remain non-blocking.
    """

    @abstractmethod
    def push_frame(self, frame: AudioFrame, *, segment_id: str) -> bool:
        """Queue one speech frame."""

    @abstractmethod
    def commit_segment(self, segment_id: str) -> bool:
        """
        Commit one completed speech segment.

        Realtime implementations commit the remote audio buffer.
        Segment implementations begin recognition using buffered audio.
        """

    @abstractmethod
    def flush(self) -> bool:
        """Discard the active, uncommitted segment."""

    @abstractmethod
    def end_input(self) -> bool:
        """Signal that no more audio frames will arrive."""

    @abstractmethod
    def __aiter__(self) -> AsyncIterator[TranscriptionEvent]:
        """Iterate normalized transcription events."""

    @abstractmethod
    async def aclose(self) -> None:
        """Close the stream and release provider resources."""

    async def __aenter__(self) -> STTStreamBase:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()
