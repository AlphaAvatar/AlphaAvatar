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

import pathlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from alphaavatar.agents.avatar.provider.errors import ModelProtocolError
from alphaavatar.agents.avatar.provider.schemas.model_input import (
    ModelFunctionCall,
    ModelFunctionOutput,
    ModelInputItem,
)
from alphaavatar.agents.memory.enums import (
    MemoryCacheType,
    MemoryOwnerKind,
    MemoryParticipantKind,
    MemoryType,
)
from alphaavatar.agents.memory.schemas import (
    MemoryContextRef,
    MemoryItem,
    MemoryOwnerRef,
    MemoryParticipantRef,
)
from alphaavatar.core.session import Participant, SessionSnapshot
from alphaavatar.core.turn.enums import TurnInputModality
from alphaavatar.core.turn.schemas import TurnEntityRef, TurnSnapshot

from .messages import MemoryMessage, memory_message, same_message
from .schemas import MemoryIdentitySnapshot

type MemoryContextItem = MemoryMessage | TurnSnapshot


def _deduplicate_keep_latest(items: list[MemoryItem]) -> list[MemoryItem]:
    # Cache retention follows activation time; historical timestamps remain unchanged.
    latest: dict[str, MemoryItem] = {}
    for item in items:
        current = latest.pop(item.memory_id, None)
        if current is None or (item.revision, item.updated_at or item.created_at) > (
            current.revision,
            current.updated_at or current.created_at,
        ):
            latest[item.memory_id] = item
        else:
            latest[item.memory_id] = current
    return list(latest.values())


def _deduplicate_refs(values):
    out, seen = [], set()
    for value in values:
        if value.key not in seen:
            seen.add(value.key)
            out.append(value)
    return out


@dataclass
class MemoryState:
    maximum_memory_num: int = 24
    _buckets: dict[MemoryType, list[MemoryItem]] = field(
        default_factory=lambda: {
            MemoryType.Avatar: [],
            MemoryType.CONVERSATION: [],
            MemoryType.TOOLS: [],
            MemoryType.ENV: [],
        }
    )

    def __post_init__(self) -> None:
        if self.maximum_memory_num <= 0:
            raise ValueError("maximum_memory_num must be positive")

    @property
    def all_items(self) -> list[MemoryItem]:
        return self.get()

    def add(self, memory_type: MemoryType, items: list[MemoryItem]) -> None:
        if not items:
            return
        bucket = self._buckets.setdefault(memory_type, [])
        bucket.extend(items)
        self._buckets[memory_type] = _deduplicate_keep_latest(bucket)[-self.maximum_memory_num :]

    def discard(self, memory_ids: Iterable[str]) -> None:
        memory_ids = set(memory_ids)
        if not memory_ids:
            return
        for memory_type, bucket in self._buckets.items():
            self._buckets[memory_type] = [
                item for item in bucket if item.memory_id not in memory_ids
            ]

    def get(
        self, *, memory_type: MemoryType | None = None, context_id: str | None = None
    ) -> list[MemoryItem]:
        items = (
            [item for bucket in self._buckets.values() for item in bucket]
            if memory_type is None
            else list(self._buckets.get(memory_type, []))
        )
        if context_id is not None:
            items = [item for item in items if item.context.context_id == context_id]
        return sorted(items, key=lambda item: item.created_at)

    def replace(self, memory_type: MemoryType, items: list[MemoryItem]) -> None:
        self._buckets[memory_type] = _deduplicate_keep_latest(items)[-self.maximum_memory_num :]

    def render(
        self, *, memory_type: MemoryType | None = None, context_id: str | None = None
    ) -> str:
        return "\n".join(
            item.render_line() for item in self.get(memory_type=memory_type, context_id=context_id)
        )


class MemoryContextState:
    def __init__(
        self,
        *,
        context: MemoryContextRef,
        provider_dir: pathlib.Path,
        owner_refs: list[MemoryOwnerRef],
        participant_refs: list[MemoryParticipantRef] | None = None,
        cache_type: MemoryCacheType = MemoryCacheType.SESSION_INTERACTION,
        participants: tuple[Participant, ...] = (),
    ) -> None:
        if not owner_refs:
            raise ValueError("Memory context requires at least one owner")

        self._context = context
        self._provider_dir = provider_dir
        self._owner_refs = _deduplicate_refs(owner_refs)
        self._participant_refs = _deduplicate_refs(participant_refs or [])
        self._participants = {
            participant.participant_id: participant for participant in participants
        }
        self._identity_sequence = 0

        dynamic_users = {p.user_id for p in participants if p.user_id is not None}
        self._owner_refs = [
            ref
            for ref in self._owner_refs
            if ref.kind is not MemoryOwnerKind.USER or ref.id not in dynamic_users
        ]
        self._participant_refs = [
            ref
            for ref in self._participant_refs
            if ref.kind is not MemoryParticipantKind.USER or ref.id not in dynamic_users
        ]

        self._cache_type = cache_type
        self._messages: list[MemoryContextItem] = []
        self._message_ids: dict[str, MemoryMessage] = {}
        self._tool_ids: dict[tuple[type, str], str] = {}
        self._call_names: dict[str, str] = {}
        self._turn_ids: dict[str, str] = {}
        self._turn_input_ids: dict[str, str] = {}
        self._turns: dict[str, TurnSnapshot] = {}
        self._message_turn_ids: dict[str, str | None] = {}

    @property
    def context(self) -> MemoryContextRef:
        return self._context

    @property
    def context_id(self) -> str:
        return self._context.context_id

    @property
    def session_id(self) -> str | None:
        return self._context.session_id

    @property
    def provider_dir(self) -> pathlib.Path:
        return self._provider_dir

    @property
    def owner_refs(self) -> list[MemoryOwnerRef]:
        return _deduplicate_refs(
            [
                *self._owner_refs,
                *(
                    MemoryOwnerRef.user(p.user_id)
                    for p in self._participants.values()
                    if p.user_id is not None
                ),
            ]
        )

    @property
    def participant_refs(self) -> list[MemoryParticipantRef]:
        return _deduplicate_refs(
            [
                *self._participant_refs,
                *(
                    MemoryParticipantRef.user(p.user_id)
                    for p in self._participants.values()
                    if p.user_id is not None
                ),
            ]
        )

    @property
    def cache_type(self) -> MemoryCacheType:
        return self._cache_type

    @property
    def messages(self) -> list[MemoryContextItem]:
        return list(self._messages)

    @property
    def message_sequence(self) -> int:
        return len(self._messages)

    def messages_between(self, start: int, end: int) -> list[MemoryContextItem]:
        if not 0 <= start <= end <= len(self._messages):
            raise ValueError(f"Invalid Memory context message range: {start}..{end}")
        return list(self._messages[start:end])

    def sync_identity(self, snapshot: SessionSnapshot, *, include_new: bool = False) -> None:
        if self.session_id != snapshot.session_id:
            return
        # These are transient associations. Durable records retain their original write evidence.
        participants = snapshot.participants
        self._participants = {
            participant_id: participant
            for participant_id, participant in participants.items()
            if include_new or participant_id in self._participants
        }
        self._identity_sequence = snapshot.sequence

    def capture_identity(
        self, messages: Sequence[MemoryContextItem] | None = None
    ) -> MemoryIdentitySnapshot:
        participants = tuple(self._participants.values())
        owner_refs, participant_refs = self.owner_refs, self.participant_refs
        actors: dict[TurnEntityRef, None] = {}
        unattributed = messages is None and any(p.user_id is None for p in participants)
        if messages is not None:
            selected: dict[str, Participant] = {}
            for item in messages:
                turn = (
                    item
                    if isinstance(item, TurnSnapshot)
                    else self._turns.get(self._message_turn_ids.get(item.id))
                )
                if turn is None or turn.modality is TurnInputModality.SYSTEM or not turn.actors:
                    unattributed = True
                    continue
                for actor in turn.actors:
                    actors[actor] = None
                    participant = self._participants.get(actor.participant_id)
                    if (
                        participant is None
                        or actor.user_id != participant.user_id
                        or actor.identity_sequence != participant.identity_sequence
                    ):
                        unattributed = True
                    else:
                        selected[participant.participant_id] = participant

            participants = tuple(selected.values())
            # Extraction does not assign each patch to a particular speaker. A mixed or
            # uncertain batch stays context-scoped rather than publishing it to every user.
            unattributed = (
                unattributed
                or any(p.user_id is None for p in participants)
                or len({p.user_id for p in participants}) != 1
            )
            owner_refs = [ref for ref in self._owner_refs if ref.kind is not MemoryOwnerKind.USER]
            owner_refs.extend(
                MemoryOwnerRef.user(p.user_id) for p in participants if p.user_id is not None
            )
            participant_refs = [
                ref for ref in self._participant_refs if ref.kind is not MemoryParticipantKind.USER
            ]
            participant_refs.extend(
                MemoryParticipantRef.user(p.user_id) for p in participants if p.user_id is not None
            )

        return MemoryIdentitySnapshot(
            sequence=self._identity_sequence,
            participants=participants,
            owner_refs=tuple(ref.model_copy(deep=True) for ref in _deduplicate_refs(owner_refs)),
            participant_refs=tuple(
                ref.model_copy(deep=True) for ref in _deduplicate_refs(participant_refs)
            ),
            actors=tuple(actors),
            unattributed=unattributed,
        )

    def add_messages(self, items: Sequence[ModelInputItem], *, turn_id: str | None = None) -> None:
        staged: dict[str, MemoryMessage] = {}
        tools: dict[tuple[type, str], str] = {}
        names: dict[str, str] = {}
        # Validate and snapshot the entire batch before advancing any processor's sequence.
        for raw in items:
            item = memory_message(raw)
            if item is None:
                continue
            if item.id in self._turn_input_ids:
                raise ModelProtocolError("Memory item identity collides with committed user input")
            previous = staged.get(item.id, self._message_ids.get(item.id))
            if previous is not None:
                if not same_message(previous, item):
                    raise ModelProtocolError(f"Conflicting Memory item replay: {item.id}")
                if item.id in self._message_ids and self._message_turn_ids[item.id] != turn_id:
                    raise ModelProtocolError("Memory record origin cannot change during replay")
                continue

            if isinstance(item, ModelFunctionCall | ModelFunctionOutput):
                name = names.get(item.call_id, self._call_names.get(item.call_id))
                if name is not None and name != item.name:
                    raise ModelProtocolError("Memory tool call/result names do not match")
                names[item.call_id] = item.name
                key = type(item), item.call_id
                previous_id = tools.get(key, self._tool_ids.get(key))
                if previous_id is not None and previous_id != item.id:
                    raise ModelProtocolError(f"Duplicate Memory tool record: {item.call_id}")
                tools[key] = item.id

            staged[item.id] = item

        self._messages.extend(staged.values())
        self._message_ids.update(staged)
        self._message_turn_ids.update((item_id, turn_id) for item_id in staged)
        self._tool_ids.update(tools)
        self._call_names.update(names)

    def add_turn(self, snapshot: TurnSnapshot) -> None:
        if not isinstance(snapshot, TurnSnapshot):
            raise TypeError("Memory user inputs require a committed TurnSnapshot")
        if snapshot.context_ids and self.context_id not in snapshot.context_ids:
            raise ValueError("Committed turn does not belong to this Memory context")
        known = self._turn_ids.get(snapshot.turn_id)
        if known is not None:
            if known != snapshot.input_id:
                raise ModelProtocolError("Turn identity was reused for another input")
            return
        if snapshot.input_id in self._turn_input_ids or snapshot.input_id in self._message_ids:
            raise ModelProtocolError("Committed turn input identity is already recorded")

        self._messages.append(snapshot)
        self._turn_ids[snapshot.turn_id] = snapshot.input_id
        self._turn_input_ids[snapshot.input_id] = snapshot.turn_id
        self._turns[snapshot.turn_id] = snapshot
