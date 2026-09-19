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

from livekit.agents.llm import ChatItem, ChatMessage, FunctionCall, FunctionCallOutput

from .enums import MemoryCacheType, MemoryOwnerKind, MemoryParticipantKind
from .schemas import MemoryContextRef, MemoryOwnerRef, MemoryParticipantRef


def _deduplicate_refs(values):
    out, seen = [], set()
    for value in values:
        if value.key not in seen:
            seen.add(value.key)
            out.append(value)
    return out


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
        self._messages: list[ChatItem] = []
        self._env_message_cursor = 0

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
    def messages(self) -> list[ChatItem]:
        return self._messages

    @property
    def message_sequence(self) -> int:
        return len(self._messages)

    def messages_between(self, start: int, end: int) -> list[ChatItem]:
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
        if isinstance(message, ChatMessage) and message.role in ("user", "assistant"):
            self._messages.append(message)
        elif isinstance(message, FunctionCall | FunctionCallOutput):
            self._messages.append(message)

    def take_pending_env_messages(self) -> list[ChatItem]:
        return self._messages[self._env_message_cursor :]

    def commit_env_messages(self) -> None:
        self._env_message_cursor = len(self._messages)
