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

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime

import numpy as np

from alphaavatar.agents.constants import FACE_BETA, SPEAKER_BETA
from alphaavatar.agents.persona.cache import PersonaCache
from alphaavatar.agents.persona.schemas import DetailsBase, UserProfile, UserRuntimeState
from alphaavatar.agents.utils import NumpyOP
from alphaavatar.core.session.schemas import Participant
from alphaavatar.core.turn.schemas import TurnSnapshot

from .profile.serialization import apply_profile_changes


class DefaultPersonaCache(PersonaCache):
    """Participant observations are independent from the current user's read-only profile."""

    def __init__(self, *, participant: Participant) -> None:
        self._participant = participant

        self._base_profile = UserProfile()
        self._observations = UserProfile()

        self._detail_fields: set[str] = set()
        self._detail_timestamps: dict[str, datetime] = {}
        self._detail_operations: dict[str, list[dict]] = {}
        self._turns: list[TurnSnapshot] = []
        self._turn_ids: set[str] = set()

    @property
    def turns(self) -> list[TurnSnapshot]:
        return self._turns

    @property
    def participant(self) -> Participant:
        return self._participant

    @participant.setter
    def participant(self, participant: Participant) -> None:
        if participant.participant_id != self._participant.participant_id:
            raise ValueError("A Persona cache cannot be transferred to another participant")
        if participant.identity_sequence != self._participant.identity_sequence:
            self._base_profile = UserProfile()
            self._observations.runtime_state = None
        self._participant = participant

    @property
    def profile(self) -> UserProfile | None:
        result = self._base_profile.model_copy(deep=True)
        if self._observations.details is not None:
            data = result.details.model_dump(mode="json") if result.details is not None else {}
            observed = self._observations.details.model_dump(mode="json")
            for name in self._detail_fields:
                changes = self._detail_operations.get(name)
                data[name] = (
                    apply_profile_changes(
                        data.get(name), changes, self._detail_timestamps[name].isoformat()
                    )
                    if changes
                    else observed.get(name)
                )
            result.details = type(self._observations.details)(**data)
        for name in ("runtime_state", "speaker_vector", "face_vector"):
            value = getattr(self._observations, name)
            if value is not None:
                setattr(result, name, deepcopy(value))
        return None if result.is_empty else result

    @property
    def observation_profile(self) -> UserProfile:
        return self._observations.model_copy(deep=True)

    @property
    def detail_fields(self) -> frozenset[str]:
        return frozenset(self._detail_fields)

    @property
    def detail_operations(self) -> dict[str, list[dict]]:
        return deepcopy(self._detail_operations)

    @property
    def detail_timestamps(self) -> dict[str, datetime]:
        return self._detail_timestamps.copy()

    @property
    def profile_details(self) -> DetailsBase | None:
        details = self._observations.details
        return details.model_copy(deep=True) if details is not None else None

    @profile_details.setter
    def profile_details(self, details: DetailsBase | None) -> None:
        previous = self._observations.details
        old = previous.model_dump() if previous is not None else {}
        new = details.model_dump() if details is not None else {}
        changed = {name for name in old.keys() | new.keys() if old.get(name) != new.get(name)}
        self.mark_profile_fields(changed, updated_at=datetime.now(UTC))
        for name in changed:
            self._detail_operations.pop(name, None)
        self._observations.details = details.model_copy(deep=True) if details is not None else None

    @property
    def profile_details_dump_value(self) -> dict:
        details = self.profile_details
        if details is None:
            return {}
        result = {}
        for name, value in details.model_dump().items():
            if isinstance(value, dict):
                result[name] = value["value"]
            elif isinstance(value, list):
                result[name] = [item["value"] for item in value if isinstance(item, dict)]
        return result

    @property
    def runtime_state(self) -> UserRuntimeState | None:
        return self._observations.runtime_state

    @runtime_state.setter
    def runtime_state(self, state: UserRuntimeState) -> None:
        self._observations.runtime_state = state.model_copy(deep=True)

    @property
    def speaker_vector(self) -> np.ndarray | None:
        return self._observations.speaker_vector

    @speaker_vector.setter
    def speaker_vector(self, vector: np.ndarray) -> None:
        self._observations.speaker_vector = self._merge_vector(
            self._observations.speaker_vector, vector, SPEAKER_BETA
        )

    @property
    def face_vector(self) -> np.ndarray | None:
        return self._observations.face_vector

    @face_vector.setter
    def face_vector(self, vector: np.ndarray) -> None:
        self._observations.face_vector = self._merge_vector(
            self._observations.face_vector, vector, FACE_BETA
        )

    @staticmethod
    def _merge_vector(current: np.ndarray | None, vector: np.ndarray, beta: float) -> np.ndarray:
        if current is not None:
            if current.shape != vector.shape:
                raise ValueError(
                    f"Identity vector shape mismatch: {current.shape} vs {vector.shape}"
                )
            vector = beta * current + (1 - beta) * vector
        return NumpyOP.l2_normalize(vector).copy()

    def set_base(self, profile: UserProfile) -> None:
        self._base_profile = profile.model_copy(deep=True)

    def clear_base(self) -> None:
        self._base_profile = UserProfile()

    def mark_profile_fields(self, fields: set[str], *, updated_at: datetime) -> None:
        self._detail_fields.update(fields)
        self._detail_timestamps.update(dict.fromkeys(fields, updated_at))

    def record_profile_operations(self, operations: dict[str, list[dict]]) -> None:
        self._detail_operations.update(deepcopy(operations))

    def snapshot(self) -> DefaultPersonaCache:
        result = DefaultPersonaCache(participant=self._participant)
        result._observations = self._observations.model_copy(deep=True)
        result._detail_fields = self._detail_fields.copy()
        result._detail_timestamps = self._detail_timestamps.copy()
        result._detail_operations = deepcopy(self._detail_operations)
        return result

    def add_turn(self, snapshot: TurnSnapshot) -> None:
        if snapshot.turn_id not in self._turn_ids:
            self._turns.append(replace(snapshot, perception_events=(), metadata={}))
            self._turn_ids.add(snapshot.turn_id)
