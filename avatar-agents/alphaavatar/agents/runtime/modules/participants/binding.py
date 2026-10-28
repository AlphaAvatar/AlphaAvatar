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


class ParticipantBindings:
    """Adapter-owned links to internal participants; unbound input remains observable."""

    def __init__(self) -> None:
        self._transports: dict[str, str] = {}
        self._sources: dict[PerceptionSourceRef, str] = {}

    def bind_transport(self, transport_id: str, participant_id: str) -> None:
        if not transport_id or not participant_id:
            raise ValueError("Transport and participant identifiers cannot be empty")
        current = self._transports.get(transport_id)
        if current is not None and current != participant_id:
            raise ValueError("Transport is already bound to another participant")
        self._transports[transport_id] = participant_id

    def bind_source(self, source: PerceptionSourceRef, participant_id: str) -> None:
        if not participant_id:
            raise ValueError("Participant identifier cannot be empty")
        current = self._sources.get(source)
        if current is not None and current != participant_id:
            raise ValueError("Source generation is already bound to another participant")
        self._sources[source] = participant_id

    def unbind_transport(self, transport_id: str) -> None:
        self._transports.pop(transport_id, None)

    def unbind_source(self, source: PerceptionSourceRef) -> None:
        self._sources.pop(source, None)

    def resolve(
        self, transport_participant_id: str | None, *, source: PerceptionSourceRef | None = None
    ) -> str | None:
        transport = self._transports.get(transport_participant_id or "")
        participant = self._sources.get(source) if source is not None else None
        if transport is not None and participant is not None and transport != participant:
            return None
        return participant if participant is not None else transport
