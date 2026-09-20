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
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TypeAlias

from livekit.agents.llm import ChatItem, ChatMessage, FunctionCall, FunctionCallOutput

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
from alphaavatar.core.turn import TurnSnapshot

MemoryContextItem: TypeAlias = ChatItem | TurnSnapshot


def _deduplicate_keep_latest(items: list[MemoryItem]) -> list[MemoryItem]:
    latest: dict[str, MemoryItem] = {}

    for item in items:
        current = latest.get(item.memory_id)

        if current is None or (
            item.revision,
            item.updated_at or item.created_at,
        ) > (
            current.revision,
            current.updated_at or current.created_at,
        ):
            latest[item.memory_id] = item

    return sorted(latest.values(), key=lambda item: item.created_at)


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
        self,
        *,
        memory_type: MemoryType | None = None,
        context_id: str | None = None,
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
        self,
        *,
        memory_type: MemoryType | None = None,
        context_id: str | None = None,
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
    ) -> None:
        if not owner_refs:
            raise ValueError("Memory context requires at least one owner")

        self._context = context
        self._provider_dir = provider_dir
        self._owner_refs = _deduplicate_refs(owner_refs)
        self._participant_refs = _deduplicate_refs(participant_refs or [])
        self._cache_type = cache_type

        self._messages: list[MemoryContextItem] = []
        self._turn_ids: set[str] = set()
        self._turn_input_ids: set[str] = set()

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
        return list(self._owner_refs)

    @property
    def participant_refs(self) -> list[MemoryParticipantRef]:
        return list(self._participant_refs)

    @property
    def cache_type(self) -> MemoryCacheType:
        return self._cache_type

    @property
    def messages(self) -> list[MemoryContextItem]:
        return self._messages

    @property
    def message_sequence(self) -> int:
        return len(self._messages)

    def messages_between(self, start: int, end: int) -> list[MemoryContextItem]:
        if not 0 <= start <= end <= len(self._messages):
            raise ValueError(f"Invalid Memory context message range: {start}..{end}")
        return list(self._messages[start:end])

    def replace_user_id(self, old_user_id: str | None, new_user_id: str) -> None:
        if not old_user_id or old_user_id == new_user_id:
            return

        self._owner_refs = _deduplicate_refs(
            [
                MemoryOwnerRef.user(new_user_id)
                if ref.kind is MemoryOwnerKind.USER and ref.id == old_user_id
                else ref
                for ref in self._owner_refs
            ]
        )
        self._participant_refs = _deduplicate_refs(
            [
                MemoryParticipantRef.user(new_user_id)
                if ref.kind is MemoryParticipantKind.USER and ref.id == old_user_id
                else ref
                for ref in self._participant_refs
            ]
        )

    def add_message(self, message: ChatItem) -> None:
        if isinstance(message, ChatMessage):
            if message.role not in {"user", "assistant"}:
                return
            if message.role == "user" and message.id in self._turn_input_ids:
                return
            self._messages.append(message)
        elif isinstance(message, FunctionCall | FunctionCallOutput):
            self._messages.append(message)

    def add_turn(self, snapshot: TurnSnapshot) -> None:
        if snapshot.turn_id in self._turn_ids:
            return

        for index, item in enumerate(self._messages):
            if (
                isinstance(item, ChatMessage)
                and item.role == "user"
                and item.id == snapshot.input_id
            ):
                self._messages[index] = snapshot
                break
        else:
            self._messages.append(snapshot)

        self._turn_ids.add(snapshot.turn_id)
        self._turn_input_ids.add(snapshot.input_id)
