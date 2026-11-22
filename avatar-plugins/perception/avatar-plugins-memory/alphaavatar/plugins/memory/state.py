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
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType

from alphaavatar.agents.avatar.provider.enums import ModelMessagePhase, ModelRole
from alphaavatar.agents.avatar.provider.errors import ModelProtocolError
from alphaavatar.agents.avatar.provider.schemas.model_input import (
    ModelAudioPart,
    ModelControlItem,
    ModelFunctionCall,
    ModelFunctionOutput,
    ModelImagePart,
    ModelInputItem,
    ModelInputMessage,
    ModelMediaPart,
    ModelProviderItem,
    ModelReasoningPart,
    ModelRefusalPart,
    ModelTemporalPart,
    ModelTextPart,
)
from alphaavatar.agents.constants import RUNTIME_CONTEXT_TOOL_NAME
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
    deduplicate_refs,
)
from alphaavatar.core.session import Participant, SessionSnapshot
from alphaavatar.core.session.schemas import IdentityBasis
from alphaavatar.core.turn.enums import TurnInputModality
from alphaavatar.core.turn.schemas import TurnEntityRef, TurnSnapshot

from .schemas import MemoryIdentitySnapshot

type MemoryMessage = ModelInputMessage | ModelFunctionCall | ModelFunctionOutput
type MemoryContextItem = MemoryMessage | TurnSnapshot


def _memory_message(item: ModelInputItem) -> MemoryMessage | None:
    """Project evidence for extraction, not Provider continuation or application instructions."""
    if isinstance(item, ModelControlItem | ModelProviderItem):
        return None
    if not isinstance(item, ModelInputMessage | ModelFunctionCall | ModelFunctionOutput):
        raise TypeError("Memory requires native model items")
    if not isinstance(item.id, str) or not item.id.strip():
        raise ValueError("Memory messages require a nonempty identity")
    if isinstance(item, ModelInputMessage):
        if not isinstance(item.role, ModelRole):
            raise TypeError("Memory message roles must use ModelRole")
        if item.phase is not None and not isinstance(item.phase, ModelMessagePhase):
            raise TypeError("Memory message phases must use ModelMessagePhase")
        # Turns are the sole user-input source. Never promote system instructions to memories.
        if item.role != ModelRole.ASSISTANT:
            return None
    else:
        if item.name == RUNTIME_CONTEXT_TOOL_NAME:
            return None
        if not all(isinstance(value, str) and value.strip() for value in (item.call_id, item.name)):
            raise ValueError("Memory tool records require call and tool identities")
        if isinstance(item, ModelFunctionCall) and not isinstance(item.arguments, str):
            raise TypeError("Memory tool arguments must be serialized text")
        if isinstance(item, ModelFunctionOutput) and type(item.is_error) is not bool:
            raise TypeError("Memory tool errors must be explicit booleans")

    changes = {}
    if isinstance(item, ModelInputMessage | ModelFunctionCall):
        if not isinstance(item.metadata, Mapping):
            raise TypeError("Memory record metadata must be a mapping")
        changes["metadata"] = MappingProxyType({})

    if isinstance(item, ModelInputMessage | ModelFunctionOutput):
        parts = []
        for part in item.parts:
            if isinstance(part, ModelReasoningPart):
                continue

            if isinstance(part, ModelTextPart | ModelRefusalPart) and not isinstance(
                part.text, str
            ):
                raise TypeError("Memory text parts must contain strings")

            if isinstance(part, ModelTextPart):
                part = replace(part, annotations=())
            elif not isinstance(
                part,
                ModelRefusalPart
                | ModelImagePart
                | ModelAudioPart
                | ModelTemporalPart
                | ModelMediaPart,
            ):
                raise TypeError("Unsupported memory content part")

            if isinstance(part, ModelImagePart | ModelAudioPart):
                part = ModelTextPart(
                    f"[media evidence: observation={part.observation.observation_id}]"
                )
            elif isinstance(part, ModelTemporalPart):
                observations = ",".join(
                    observation.observation_id
                    for value in part.slices
                    for observation in value.observations
                )
                part = ModelTextPart(
                    f"[temporal evidence: observations={observations}; not decoded here]"
                )
            elif isinstance(part, ModelMediaPart):
                part = ModelTextPart(
                    f"[media evidence: {part.kind.value}, {part.mime_type}; not decoded here]"
                )

            parts.append(part)
        if not parts and isinstance(item, ModelInputMessage):
            return None
        changes["parts"] = tuple(parts)
    return replace(item, **changes)


def _identity(
    participant_id: str | None, user_id: str | None, identity_revision: int | None
) -> TurnEntityRef:
    """An input's participant by its identity alone: inputs from one person are one entry,
    whatever device or entity named them, and all anonymous ones another."""
    return TurnEntityRef(
        participant_id=participant_id, user_id=user_id, identity_revision=identity_revision
    )


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


@dataclass(frozen=True, slots=True)
class _Record:
    """A model or tool record as its context holds it, with the Turn it answers and the
    identity it was admitted with."""

    message: MemoryMessage
    turn_id: str | None
    basis: IdentityBasis | None


@dataclass
class MemoryState:
    """The latest items of each memory type, at most ``maximum_memory_num`` each, for recall
    and the extraction prompts."""

    maximum_memory_num: int = 24
    _buckets: dict[MemoryType, list[MemoryItem]] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        if self.maximum_memory_num <= 0:
            raise ValueError("maximum_memory_num must be positive")

    def add(self, memory_type: MemoryType, items: list[MemoryItem]) -> None:
        if not items:
            return
        bucket = [*self._buckets.get(memory_type, []), *items]
        self._buckets[memory_type] = _deduplicate_keep_latest(bucket)[-self.maximum_memory_num :]

    def discard(self, memory_ids: Iterable[str]) -> None:
        memory_ids = set(memory_ids)
        if not memory_ids:
            return
        for memory_type, bucket in self._buckets.items():
            self._buckets[memory_type] = [
                item for item in bucket if item.memory_id not in memory_ids
            ]

    def get(self, *, memory_type: MemoryType, context_id: str | None = None) -> list[MemoryItem]:
        items = self._buckets.get(memory_type, [])
        if context_id is not None:
            items = [item for item in items if item.context.context_id == context_id]
        return sorted(items, key=lambda item: item.created_at)


class MemoryContextState:
    """One Memory context: its committed Turns and model or tool records in arrival order, and
    whom they are from."""

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
        participant_refs = participant_refs or []
        if not owner_refs:
            raise ValueError("Memory context requires at least one owner")
        if any(ref.kind is MemoryOwnerKind.USER for ref in owner_refs) or any(
            ref.kind is MemoryParticipantKind.USER for ref in participant_refs
        ):
            raise ValueError("A Memory context's users are its participants, never fixed refs")

        # The context, where its provider writes and how its records are cached.
        self._context = context
        self._provider_dir = provider_dir
        self._cache_type = cache_type

        # Its fixed owners and participants; its users are its participants', as they stand.
        self._owner_refs = deduplicate_refs(owner_refs)
        self._participant_refs = deduplicate_refs(participant_refs)
        self._participants = {
            participant.participant_id: participant for participant in participants
        }
        self._session_sequence = 0

        # What it holds, in arrival order: Turns by ID and their inputs, records by ID.
        self._messages: list[MemoryContextItem] = []
        self._turns: dict[str, TurnSnapshot] = {}
        self._input_ids: set[str] = set()
        self._records: dict[str, _Record] = {}

        # Tool calls and results pair by call: each record's ID and each call's tool name.
        self._tool_ids: dict[tuple[type, str], str] = {}
        self._call_names: dict[str, str] = {}

    @property
    def context(self) -> MemoryContextRef:
        return self._context

    @property
    def context_id(self) -> str:
        return self._context.context_id

    @property
    def provider_dir(self) -> pathlib.Path:
        return self._provider_dir

    @property
    def cache_type(self) -> MemoryCacheType:
        return self._cache_type

    @property
    def message_sequence(self) -> int:
        return len(self._messages)

    def _refs(
        self, users: Iterable[str]
    ) -> tuple[tuple[MemoryOwnerRef, ...], tuple[MemoryParticipantRef, ...]]:
        """Its fixed owners and participants, with the users, each copied."""
        users = tuple(users)
        owners = [*self._owner_refs, *(MemoryOwnerRef.user(user) for user in users)]
        participants = [
            *self._participant_refs,
            *(MemoryParticipantRef.user(user) for user in users),
        ]
        return (
            tuple(ref.model_copy(deep=True) for ref in deduplicate_refs(owners)),
            tuple(ref.model_copy(deep=True) for ref in deduplicate_refs(participants)),
        )

    def messages_between(self, start: int, end: int) -> list[MemoryContextItem]:
        if not 0 <= start <= end <= len(self._messages):
            raise ValueError(f"Invalid Memory context message range: {start}..{end}")
        return list(self._messages[start:end])

    def get_turn(self, turn_id: str) -> TurnSnapshot | None:
        return self._turns.get(turn_id)

    def sync_identity(self, snapshot: SessionSnapshot, *, include_new: bool = False) -> None:
        if self._context.session_id != snapshot.session_id:
            return

        # These are transient associations. Durable records retain their original write evidence.
        participants = snapshot.participants
        self._participants = {
            participant_id: participant
            for participant_id, participant in participants.items()
            if include_new or participant_id in self._participants
        }
        self._session_sequence = snapshot.sequence

    def capture_identity(
        self,
        messages: Sequence[MemoryContextItem] | None = None,
        *,
        of_turn: Callable[[TurnSnapshot], tuple[TurnEntityRef, ...]] | None = None,
    ) -> MemoryIdentitySnapshot:
        """Whom the messages are from: each user input by its Turn's participants as they
        stand now (``of_turn``), each model or tool record by the identity it was admitted
        with. Without messages, the context's participants."""
        if messages is None:
            found = {
                _identity(p.participant_id, p.user_id, p.identity_revision): None
                for p in self._participants.values()
            }
            unattributed = any(p.user_id is None for p in self._participants.values())
            people = self._participants.values()
        else:
            if of_turn is None:
                raise ValueError("A batch's participants are read from its Turns")
            found, selected, unattributed = {}, {}, False
            for item in messages:
                if isinstance(item, TurnSnapshot):
                    turn, basis = item, None
                else:
                    record = self._records.get(item.id)
                    turn = self._turns.get(record.turn_id) if record is not None else None
                    basis = record.basis if record is not None else None
                if basis is not None:
                    entries = tuple(
                        _identity(ref.participant_id, ref.user_id, ref.identity_revision)
                        for ref in basis.participants
                    )
                elif turn is not None and turn.modality is not TurnInputModality.SYSTEM:
                    entries = tuple(
                        _identity(entry.participant_id, entry.user_id, entry.identity_revision)
                        for entry in of_turn(turn)
                    )
                else:
                    entries = ()
                if not entries:
                    unattributed = True
                    continue

                for entry in entries:
                    found[entry] = None
                    participant = self._participants.get(entry.participant_id)
                    if (
                        participant is None
                        or entry.user_id != participant.user_id
                        or entry.identity_revision != participant.identity_revision
                    ):
                        unattributed = True
                    else:
                        selected[participant.participant_id] = participant

            # Extraction does not assign each patch to a particular speaker. A mixed or
            # uncertain batch stays context-scoped rather than publishing it to every user.
            unattributed = (
                unattributed
                or any(p.user_id is None for p in selected.values())
                or len({p.user_id for p in selected.values()}) != 1
            )
            people = selected.values()

        owner_refs, participant_refs = self._refs(
            p.user_id for p in people if p.user_id is not None
        )
        return MemoryIdentitySnapshot(
            sequence=self._session_sequence,
            participants=tuple(found),
            owner_refs=owner_refs,
            participant_refs=participant_refs,
            unattributed=unattributed,
        )

    def add_messages(
        self,
        items: Sequence[ModelInputItem],
        *,
        turn_id: str | None = None,
        identity_basis: IdentityBasis | None = None,
    ) -> None:
        if identity_basis is not None and not isinstance(identity_basis, IdentityBasis):
            raise TypeError("Memory record provenance requires IdentityBasis")
        staged: dict[str, MemoryMessage] = {}
        tools: dict[tuple[type, str], str] = {}
        names: dict[str, str] = {}
        # Validate and snapshot the entire batch before advancing any processor's sequence.
        for raw in items:
            item = _memory_message(raw)
            if item is None:
                continue
            if item.id in self._input_ids:
                raise ModelProtocolError("Memory item identity collides with committed user input")

            recorded = self._records.get(item.id)
            previous = staged.get(item.id, recorded.message if recorded is not None else None)
            if previous is not None:
                # The compact buffer holds frozen text and scalar evidence only.
                if type(previous) is not type(item) or previous != item:
                    raise ModelProtocolError(f"Conflicting Memory item replay: {item.id}")
                if recorded is not None and (recorded.turn_id, recorded.basis) != (
                    turn_id,
                    identity_basis,
                ):
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
        self._records.update(
            (item_id, _Record(item, turn_id, identity_basis)) for item_id, item in staged.items()
        )
        self._tool_ids.update(tools)
        self._call_names.update(names)

    def add_turn(self, snapshot: TurnSnapshot) -> None:
        if not isinstance(snapshot, TurnSnapshot):
            raise TypeError("Memory user inputs require a committed TurnSnapshot")
        if snapshot.context_ids and self.context_id not in snapshot.context_ids:
            raise ValueError("Committed turn does not belong to this Memory context")
        known = self._turns.get(snapshot.turn_id)
        if known is not None:
            if known.input_id != snapshot.input_id:
                raise ModelProtocolError("Turn identity was reused for another input")
            return
        if snapshot.input_id in self._input_ids or snapshot.input_id in self._records:
            raise ModelProtocolError("Committed turn input identity is already recorded")

        self._messages.append(snapshot)
        self._turns[snapshot.turn_id] = snapshot
        self._input_ids.add(snapshot.input_id)
