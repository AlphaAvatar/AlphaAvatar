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
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

import numpy as np

from alphaavatar.agents.constants import FACE_BETA, SPEAKER_BETA
from alphaavatar.agents.persona.cache import PersonaCache
from alphaavatar.agents.persona.schemas import DetailsBase, UserProfile, UserRuntimeState
from alphaavatar.agents.utils import NumpyOP
from alphaavatar.core.session.schemas import Participant
from alphaavatar.core.turn.schemas import TurnSnapshot

from .profile import UserProfileDetails
from .profile.serialization import field_metadata, merge_profile_field
from .vectors import WeightedMean


@dataclass(frozen=True, slots=True)
class _BaseProfile:
    """The current identity's profile as the store returned it, read-only for the session, with
    what the cache knows about that load. An empty profile is also what no load leaves, so
    ``loaded`` tells a user without a stored speaker vector from one never read."""

    profile: UserProfile = field(default_factory=UserProfile)
    loaded: bool = False

    def speaker_vector_only(self) -> _BaseProfile:
        """A write's copy: the stored speaker vector alone; no profile details merge into a save."""
        vector = self.profile.speaker_vector
        stored = UserProfile(speaker_vector=None if vector is None else vector.copy())
        return _BaseProfile(stored, self.loaded)


class DefaultPersonaCache(PersonaCache):
    """Participant observations are independent from the current user's read-only profile."""

    def __init__(self, *, participant: Participant) -> None:
        self._participant = participant

        self._base = _BaseProfile()
        self._observations = UserProfile()
        self._voice: WeightedMean | None = None

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
            self._base = _BaseProfile()
            self._observations.runtime_state = None
        self._participant = participant

    @property
    def profile(self) -> UserProfile | None:
        result = self._base.profile.model_copy(deep=True)
        if self._observations.details is not None:
            data = result.details.model_dump(mode="json") if result.details is not None else {}
            observed = self._observations.details.model_dump(mode="json")
            metadata = deepcopy(getattr(result.details, "_field_metadata", {}))
            observed_metadata = getattr(self._observations.details, "_field_metadata", {})
            for name in self._detail_fields:
                incoming = {
                    **observed_metadata.get(name, {}),
                    "value": observed.get(name),
                    "updated_at": self._detail_timestamps[name].isoformat(),
                    "changes": self._detail_operations.get(name, []),
                }
                data[name], metadata[name] = merge_profile_field(
                    data.get(name), metadata.get(name, {}), incoming
                )
            result.details = type(self._observations.details)(**data)
            result.details._field_metadata = metadata
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
        profile = self.profile
        return profile.details if profile is not None else None

    @profile_details.setter
    def profile_details(self, details: DetailsBase | None) -> None:
        previous = self.profile_details
        old = previous.model_dump(mode="json") if previous is not None else {}
        new = details.model_dump(mode="json") if details is not None else {}
        changed = {name for name in old.keys() | new.keys() if old.get(name) != new.get(name)}
        if not changed:
            return

        observed = self._observations.details
        data = observed.model_dump(mode="json") if observed is not None else {}
        metadata = deepcopy(getattr(observed, "_field_metadata", {}))
        for name in changed:
            update = field_metadata(new.get(name))
            if new.get(name) in (None, []):
                update["source"] = "chat"
            stamp = update.get("updated_at") or datetime.now(UTC).isoformat()
            update.update(value=new.get(name), updated_at=stamp, changes=[])
            value, effective = merge_profile_field(
                old.get(name), getattr(previous, "_field_metadata", {}).get(name, {}), update
            )
            if value == old.get(name):
                continue
            data[name], metadata[name] = value, effective
            self.mark_profile_fields({name}, updated_at=datetime.fromisoformat(stamp))
            self._detail_operations.pop(name, None)

        model = type(details or previous)
        self._observations.details = model(**data)
        self._observations.details._field_metadata = metadata

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

    @property
    def voice(self) -> WeightedMean | None:
        """The participant's speech in this session: its segments' vectors, by their seconds."""
        return None if self._voice is None else self._voice.copy()

    @voice.setter
    def voice(self, voice: WeightedMean) -> None:
        self._voice = voice.copy()
        self._observations.speaker_vector = voice.vector

    @property
    def saved_speaker_vector(self) -> np.ndarray | None:
        """The speaker vector a save writes, or None to leave the stored one as it is.

        While the session runs, its vector stays apart from the user's stored speaker vector; only
        the save merges it into the one loaded for this same identity, ``SPEAKER_BETA`` of the
        stored. A user with none stored takes the session's vector. Without a completed load the
        stored vector is unknown, so it is not overwritten."""
        observed = self._observations.speaker_vector
        if observed is None or not self._base.loaded:
            return None
        loaded = self._base.profile.speaker_vector
        if loaded is None:
            return observed.copy()
        return self._merge_vector(loaded, observed, SPEAKER_BETA)

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

    def add_speaker_vector(self, vector: np.ndarray, seconds: float) -> None:
        if self._voice is None:
            self._voice = WeightedMean.of(vector, seconds)
        else:
            self._voice.add(vector, seconds)
        self._observations.speaker_vector = self._voice.vector

    def set_base(self, profile: UserProfile) -> None:
        self._base = _BaseProfile(profile.model_copy(deep=True), loaded=True)

    def clear_base(self) -> None:
        self._base = _BaseProfile()

    def set_new_user(self) -> None:
        """The identity's user is new in this session: the store holds nothing of it, which is
        known without a load (one still running when the session ends never completes)."""
        if not self._base.loaded:
            self._base = _BaseProfile(loaded=True)

    def mark_profile_fields(self, fields: set[str], *, updated_at: datetime) -> None:
        self._detail_fields.update(fields)
        self._detail_timestamps.update(dict.fromkeys(fields, updated_at))

    def record_profile_operations(self, operations: dict[str, list[dict]]) -> None:
        if operations and self._observations.details is None:
            self._observations.details = UserProfileDetails()
        self._detail_operations.update(deepcopy(operations))

    def snapshot(self) -> DefaultPersonaCache:
        result = DefaultPersonaCache(participant=self._participant)
        result._observations = self._observations.model_copy(deep=True)
        result._voice = self.voice
        result._base = self._base.speaker_vector_only()
        result._detail_fields = self._detail_fields.copy()
        result._detail_timestamps = self._detail_timestamps.copy()
        result._detail_operations = deepcopy(self._detail_operations)
        return result

    def add_turn(self, snapshot: TurnSnapshot) -> None:
        if snapshot.turn_id not in self._turn_ids:
            self._turns.append(replace(snapshot, perception_events=(), metadata={}))
            self._turn_ids.add(snapshot.turn_id)
