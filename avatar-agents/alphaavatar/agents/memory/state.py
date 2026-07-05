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

from alphaavatar.agents.utils import time_str_to_datetime

from .enum.memory_type import MemoryType
from .schema.memory_item import MemoryItem


def deduplicate_keep_latest(items: list[MemoryItem]) -> list[MemoryItem]:
    latest_items: dict[str, MemoryItem] = {}

    for item in items:
        if item.memory_id not in latest_items:
            latest_items[item.memory_id] = item
            continue

        current_time = time_str_to_datetime(item.timestamp)
        existing_time = time_str_to_datetime(latest_items[item.memory_id].timestamp)

        if current_time > existing_time:
            latest_items[item.memory_id] = item

    return sorted(latest_items.values(), key=lambda x: time_str_to_datetime(x.timestamp))


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
        session_id: str | None = None,
        updated: bool | None = None,
    ) -> list[MemoryItem]:
        if memory_type is None:
            items = [item for bucket in self._buckets.values() for item in bucket]
        else:
            items = list(self._buckets.get(memory_type, []))

        if session_id is not None:
            items = [item for item in items if item.session_id == session_id]

        if updated is not None:
            items = [item for item in items if item.updated is updated]

        return sorted(items, key=lambda x: time_str_to_datetime(x.timestamp))

    def render(
        self,
        *,
        memory_type: MemoryType | None = None,
        session_id: str | None = None,
        updated: bool | None = None,
    ) -> str:
        lines: list[str] = []

        for item in self.get(
            memory_type=memory_type,
            session_id=session_id,
            updated=updated,
        ):
            sub_memory = ""
            sub_memory += f"Timestamp: {item.timestamp}; "
            if item.topic:
                sub_memory += f"Topic: {item.topic}; "
            sub_memory += f"Content: {item.value}"
            lines.append(sub_memory.strip())

        return "\n".join(lines)

    def mark_saved(self, memory_ids: set[str]) -> None:
        for item in self.all_items:
            if item.memory_id in memory_ids:
                item.updated = False
