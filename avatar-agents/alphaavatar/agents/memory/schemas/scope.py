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

from typing import TYPE_CHECKING

from pydantic import BaseModel, model_validator

from ..enums import MemoryScopeKind

if TYPE_CHECKING:
    from .context import MemoryContextRef


class MemoryScope(BaseModel):
    kind: MemoryScopeKind
    scope_id: str | None = None

    @model_validator(mode="after")
    def _validate_scope(self) -> MemoryScope:
        if self.kind is MemoryScopeKind.OWNER:
            if self.scope_id is not None:
                raise ValueError("owner scope must not set scope_id")
            return self

        scope_id = str(self.scope_id or "").strip()
        if not scope_id:
            raise ValueError(f"{self.kind.value} scope requires scope_id")

        self.scope_id = scope_id
        return self

    @property
    def key(self) -> str:
        if self.kind is MemoryScopeKind.OWNER:
            return "owner:*"
        return f"{self.kind.value}:{self.scope_id}"

    @staticmethod
    def applicable_keys(context: MemoryContextRef) -> tuple[str, str, str]:
        return (
            "owner:*",
            f"conversation:{context.conversation_id}",
            f"context:{context.context_id}",
        )

    @classmethod
    def owner(cls) -> MemoryScope:
        return cls(kind=MemoryScopeKind.OWNER)

    @classmethod
    def conversation(cls, conversation_id: str) -> MemoryScope:
        return cls(kind=MemoryScopeKind.CONVERSATION, scope_id=conversation_id)

    @classmethod
    def context(cls, context_id: str) -> MemoryScope:
        return cls(kind=MemoryScopeKind.CONTEXT, scope_id=context_id)

    def applies_to(self, context: MemoryContextRef) -> bool:
        if self.kind is MemoryScopeKind.OWNER:
            return True
        if self.kind is MemoryScopeKind.CONVERSATION:
            return self.scope_id == context.conversation_id
        return self.scope_id == context.context_id
