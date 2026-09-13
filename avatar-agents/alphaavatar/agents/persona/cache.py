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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np
    from livekit.agents.llm import ChatItem

    from alphaavatar.agents.runtime.session_runtime import ParticipantInfo

    from .schemas import DetailsBase, UserProfile, UserRuntimeState


class PersonaCache(ABC):
    @property
    @abstractmethod
    def messages(self) -> list[ChatItem]: ...

    @property
    @abstractmethod
    def participant(self) -> ParticipantInfo: ...

    @participant.setter
    @abstractmethod
    def participant(self, participant: ParticipantInfo) -> None: ...

    @property
    @abstractmethod
    def profile(self) -> UserProfile | None: ...

    @profile.setter
    @abstractmethod
    def profile(self, profile: UserProfile) -> None: ...

    @property
    @abstractmethod
    def profile_details(self) -> DetailsBase | None: ...

    @profile_details.setter
    @abstractmethod
    def profile_details(self, profile_details: DetailsBase | None) -> None: ...

    @property
    @abstractmethod
    def profile_details_dump_value(self) -> dict[str, Any]: ...

    @property
    @abstractmethod
    def runtime_state(self) -> UserRuntimeState | None: ...

    @runtime_state.setter
    @abstractmethod
    def runtime_state(self, runtime_state: UserRuntimeState) -> None: ...

    @property
    @abstractmethod
    def speaker_vector(self) -> np.ndarray | None: ...

    @speaker_vector.setter
    @abstractmethod
    def speaker_vector(self, vector: np.ndarray) -> None: ...

    @property
    @abstractmethod
    def face_vector(self) -> np.ndarray | None: ...

    @face_vector.setter
    @abstractmethod
    def face_vector(self, vector: np.ndarray) -> None: ...

    @abstractmethod
    def add_message(self, message: ChatItem) -> None: ...
