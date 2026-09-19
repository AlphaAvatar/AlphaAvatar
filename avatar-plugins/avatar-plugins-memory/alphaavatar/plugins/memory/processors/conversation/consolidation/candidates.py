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

from collections.abc import Iterable

from alphaavatar.agents.memory.enums import MemoryKind
from alphaavatar.agents.memory.schemas import MemoryItem, MemorySearchHit


class RecalledCandidateCache:
    def __init__(self) -> None:
        self._by_id: dict[str, MemoryItem] = {}

    def record(self, records: Iterable[MemoryItem]) -> None:
        for record in records:
            if record.kind is not MemoryKind.CONSOLIDATED:
                continue

            current = self._by_id.get(record.memory_id)
            if current is None or record.revision >= current.revision:
                self._by_id[record.memory_id] = record

    def candidates(self) -> list[MemoryItem]:
        return list(self._by_id.values())

    def clear(self) -> None:
        self._by_id.clear()

    def __len__(self) -> int:
        return len(self._by_id)


def filter_hits(
    hits: list[MemorySearchHit],
    *,
    threshold: float,
    limit: int,
) -> list[MemorySearchHit]:
    if limit <= 0:
        return []

    return [hit for hit in hits if hit.score >= threshold][:limit]


def consolidated_from_hits(
    all_hits: list[list[MemorySearchHit]],
    *,
    threshold: float,
    limit: int,
) -> list[MemoryItem]:
    return merge_candidates(
        hit.memory
        for hits in all_hits
        for hit in filter_hits(
            hits,
            threshold=threshold,
            limit=limit,
        )
        if hit.memory.kind is MemoryKind.CONSOLIDATED
    )


def merge_candidates(
    *groups: Iterable[MemoryItem],
) -> list[MemoryItem]:
    merged: dict[str, MemoryItem] = {}

    for group in groups:
        for memory in group:
            if memory.kind is not MemoryKind.CONSOLIDATED:
                continue

            current = merged.get(memory.memory_id)
            if current is None or memory.revision >= current.revision:
                merged[memory.memory_id] = memory

    return list(merged.values())
