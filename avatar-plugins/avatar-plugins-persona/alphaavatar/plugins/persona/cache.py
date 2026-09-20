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

import numpy as np

from alphaavatar.agents.constants import FACE_BETA, SPEAKER_BETA
from alphaavatar.agents.persona.cache import PersonaCache
from alphaavatar.agents.persona.schemas.user_profile import (
    DetailsBase,
    UserProfile,
    UserRuntimeState,
)
from alphaavatar.agents.runtime.session_runtime import ParticipantInfo
from alphaavatar.agents.utils import NumpyOP
from alphaavatar.core.turn import TurnSnapshot


class DefaultPersonaCache(PersonaCache):
    def __init__(
        self,
        *,
        participant: ParticipantInfo,
        user_profile: UserProfile,
    ):
        self._participant = participant
        self._user_profile = user_profile

        self._turns: list[TurnSnapshot] = []
        self._turn_ids: set[str] = set()

    @property
    def turns(self) -> list[TurnSnapshot]:
        return self._turns

    @property
    def participant(self) -> ParticipantInfo:
        return self._participant

    @property
    def profile(self) -> UserProfile | None:
        if self._user_profile is None or self._user_profile.is_empty:
            return None

        if (
            self._user_profile.details is not None
            or self._user_profile.runtime_state is not None
            or self._user_profile.speaker_vector is not None
            or self._user_profile.face_vector is not None
        ):
            return self._user_profile

        return None

    @property
    def profile_details(self) -> DetailsBase | None:
        return self._user_profile.details

    @property
    def profile_details_dump_value(self) -> dict:
        if self.profile_details:
            json_dump = self.profile_details.model_dump()
            json_dump_value = {}
            for key in json_dump:
                val = json_dump[key]
                if val is None:
                    continue

                if isinstance(val, dict):
                    json_dump_value[key] = val["value"]
                elif isinstance(val, list):
                    json_dump_value[key] = [x["value"] for x in val if isinstance(x, dict)]

            return json_dump_value
        else:
            return {}

    @property
    def runtime_state(self) -> UserRuntimeState | None:
        return self._user_profile.runtime_state

    @property
    def speaker_vector(self) -> np.ndarray | None:
        return self._user_profile.speaker_vector

    @property
    def face_vector(self) -> np.ndarray | None:
        return self._user_profile.face_vector

    @participant.setter
    def participant(self, participant: ParticipantInfo):
        self._participant = participant

    @profile.setter
    def profile(self, profile: UserProfile):
        self._user_profile = profile

    @profile_details.setter
    def profile_details(self, profile_details: DetailsBase | None):
        self._user_profile.details = profile_details

    @runtime_state.setter
    def runtime_state(self, runtime_state: UserRuntimeState):
        self._user_profile.runtime_state = runtime_state

    @speaker_vector.setter
    def speaker_vector(self, vector: np.ndarray):
        if self._user_profile is None:
            self._user_profile = UserProfile()

        current = getattr(self._user_profile, "speaker_vector", None)
        if current is None:
            self._user_profile.speaker_vector = vector
        else:
            if current.shape != vector.shape:
                raise ValueError(
                    f"speaker_vector shape mismatch: {current.shape} vs {vector.shape}"
                )
            self._user_profile.speaker_vector = NumpyOP.l2_normalize(
                SPEAKER_BETA * current + (1 - SPEAKER_BETA) * vector
            )

    @face_vector.setter
    def face_vector(self, vector: np.ndarray):
        if self._user_profile is None:
            self._user_profile = UserProfile()

        current = getattr(self._user_profile, "face_vector", None)
        if current is None:
            self._user_profile.face_vector = NumpyOP.l2_normalize(vector)
        else:
            if current.shape != vector.shape:
                raise ValueError(f"face_vector shape mismatch: {current.shape} vs {vector.shape}")

            self._user_profile.face_vector = NumpyOP.l2_normalize(
                FACE_BETA * current + (1 - FACE_BETA) * vector
            )

    def add_turn(self, snapshot: TurnSnapshot) -> None:
        if snapshot.turn_id in self._turn_ids:
            return
        self._turns.append(snapshot)
        self._turn_ids.add(snapshot.turn_id)
