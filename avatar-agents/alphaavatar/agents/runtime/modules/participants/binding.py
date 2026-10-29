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

from alphaavatar.core.env.schemas import PerceptionSourceRef
from alphaavatar.core.session.schemas import validate_identity


class ParticipantBindings:
    """Simple links to participant IDs; identity and lifecycle belong to their runtimes."""

    def __init__(self, *, max_entities: int = 1024, max_devices: int = 256) -> None:
        if any(type(value) is not int or value <= 0 for value in (max_entities, max_devices)):
            raise ValueError("Participant binding limits must be positive integers")

        self._max_entities, self._max_devices = max_entities, max_devices
        self._devices: dict[str, str] = {}
        self._entities: dict[tuple[PerceptionSourceRef, str], str] = {}

    def bind_device(self, device_id: str, participant_id: str) -> None:
        validate_identity(device_id, name="device_id")
        validate_identity(participant_id, name="participant_id")
        previous = self._devices.get(device_id)
        if previous is not None and previous != participant_id:
            raise ValueError("Device endpoint is already bound to another participant")
        if previous is None and len(self._devices) >= self._max_devices:
            raise RuntimeError("Participant endpoint capacity reached")
        self._devices[device_id] = participant_id

    def get_device(self, device_id: str) -> str | None:
        return self._devices.get(device_id)

    def check_entity(self, source: PerceptionSourceRef, entity_id: str) -> None:
        if not isinstance(entity_id, str) or not entity_id:
            raise ValueError("Perception entity identifier must be a nonempty string")
        if (source, entity_id) not in self._entities and len(self._entities) >= self._max_entities:
            raise RuntimeError("Participant entity capacity reached")

    def bind_entity(self, source: PerceptionSourceRef, entity_id: str, participant_id: str) -> None:
        validate_identity(participant_id, name="participant_id")
        self.check_entity(source, entity_id)
        key = (source, entity_id)
        previous = self._entities.get(key)
        if previous is not None and previous != participant_id:
            raise ValueError("Entity is already bound to another participant")
        self._entities[key] = participant_id

    def get_entity(self, source: PerceptionSourceRef, entity_id: str) -> str | None:
        return self._entities.get((source, entity_id))

    def release_entity(self, source: PerceptionSourceRef, entity_id: str) -> None:
        self._entities.pop((source, entity_id), None)

    def release_source(self, source: PerceptionSourceRef) -> None:
        self._entities = {key: value for key, value in self._entities.items() if key[0] != source}

    def clear(self) -> None:
        self._devices.clear()
        self._entities.clear()
