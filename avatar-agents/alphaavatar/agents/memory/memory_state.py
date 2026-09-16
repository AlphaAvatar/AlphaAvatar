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

from dataclasses import dataclass, field

from .enums.memory_type import MemoryType
from .schemas.memory_item import MemoryItem


def deduplicate_keep_latest(items: list[MemoryItem]) -> list[MemoryItem]:
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
        self._buckets[memory_type] = deduplicate_keep_latest(bucket)[-self.maximum_memory_num :]

    def replace(self, memory_type: MemoryType, items: list[MemoryItem]) -> None:
        self._buckets[memory_type] = deduplicate_keep_latest(items)[-self.maximum_memory_num :]

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

    def render(
        self,
        *,
        memory_type: MemoryType | None = None,
        context_id: str | None = None,
    ) -> str:
        return "\n".join(
            item.render_line() for item in self.get(memory_type=memory_type, context_id=context_id)
        )
