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

from alphaavatar.core.session.schemas import validate_identity

from .schemas import DeviceId, EntityId, EntityKind, ParticipantId


class ParticipantBindings:
    """Simple links to participant IDs; identity and lifecycle belong to their runtimes. An
    entity belongs to one participant on whatever source it is seen, and a participant has at
    most one entity of each kind."""

    def __init__(self, *, max_entities: int = 1024, max_devices: int = 256) -> None:
        if any(type(value) is not int or value <= 0 for value in (max_entities, max_devices)):
            raise ValueError("Participant binding limits must be positive integers")

        self._max_entities = max_entities
        self._max_devices = max_devices

        self._devices: dict[DeviceId, ParticipantId] = {}
        self._entities: dict[EntityId, tuple[ParticipantId, EntityKind]] = {}
        self._kinds: dict[ParticipantId, dict[EntityKind, EntityId]] = {}

    def check_device(self, device_id: str, participant_id: str) -> None:
        validate_identity(device_id, name="device_id")
        validate_identity(participant_id, name="participant_id")
        previous = self._devices.get(device_id)
        if previous is not None and previous != participant_id:
            raise ValueError("Device is already bound to another participant")
        if previous is None and len(self._devices) >= self._max_devices:
            raise RuntimeError("Participant device capacity reached")

    def bind_device(self, device_id: str, participant_id: str) -> None:
        self.check_device(device_id, participant_id)
        self._devices[device_id] = participant_id

    def get_device(self, device_id: str) -> ParticipantId | None:
        return self._devices.get(device_id)

    def has_participant(self, participant_id: str) -> bool:
        return participant_id in self._devices.values() or participant_id in self._kinds

    def check_entity(self, entity_id: str, kind: str, participant_id: str | None = None) -> None:
        """Whether the entity can be bound as this kind, to this participant when one is named:
        a bound entity keeps its participant and kind, and a participant takes no second entity
        of a kind it has."""
        if not isinstance(entity_id, str) or not entity_id:
            raise ValueError("Perception entity identifier must be a nonempty string")
        bound = self._entities.get(entity_id)
        if bound is not None:
            if participant_id is not None and bound[0] != participant_id:
                raise ValueError("Entity is already bound to another participant")
            if bound[1] != kind:
                raise ValueError("Entity is already bound as another kind")
            return
        if participant_id is not None and kind in self._kinds.get(participant_id, {}):
            raise ValueError(f"Participant already has a {kind} entity")
        if len(self._entities) >= self._max_entities:
            raise RuntimeError("Participant entity capacity reached")

    def bind_entity(self, entity_id: str, participant_id: str, kind: str) -> None:
        validate_identity(participant_id, name="participant_id")
        self.check_entity(entity_id, kind, participant_id)
        self._entities[entity_id] = (participant_id, kind)
        self._kinds.setdefault(participant_id, {})[kind] = entity_id

    def get_entity(self, entity_id: str) -> ParticipantId | None:
        bound = self._entities.get(entity_id)
        return None if bound is None else bound[0]

    def release_entity(self, entity_id: str) -> ParticipantId | None:
        bound = self._entities.pop(entity_id, None)
        if bound is None:
            return None
        participant_id, kind = bound
        kinds = self._kinds[participant_id]
        del kinds[kind]
        if not kinds:
            del self._kinds[participant_id]
        return participant_id

    def clear(self) -> None:
        self._devices.clear()
        self._entities.clear()
        self._kinds.clear()
