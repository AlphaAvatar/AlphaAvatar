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

from alphaavatar.agents.memory import MemoryItem, MemoryNote

from ..memory_op import rebuild_from_items

# Where the note-consolidation stage gets its candidate notes from.


class RecallLedger:
    """Every memory recalled during a session, without the MemoryState caps.

    MemoryState is a rendering view: it caps each bucket at maximum_memory_num
    and keeps the most recent by timestamp, so the oldest records get evicted
    first -- and those are exactly the ones most likely to need updating. The
    candidate source therefore keeps its own unbounded tally.
    """

    def __init__(self) -> None:
        self._by_id: dict[str, MemoryItem] = {}

    def record(self, records: Iterable[MemoryItem]) -> None:
        for record in records:
            if record.memory_id:
                self._by_id[record.memory_id] = record

    def notes(self) -> list[MemoryNote]:
        return [r for r in self._by_id.values() if isinstance(r, MemoryNote)]

    def __len__(self) -> int:
        return len(self._by_id)


def filter_hits(
    hits: list[dict],
    *,
    threshold: float,
    limit: int,
) -> list[dict]:
    kept = [hit for hit in hits if float(hit.get("score", 0.0)) >= threshold]
    return kept[:limit]


def notes_from_hits(
    all_hits: list[list[dict]],
    *,
    threshold: float,
    limit: int,
) -> list[MemoryNote]:
    """Flatten per-item nearest-neighbour hits into a deduplicated note set."""
    rows: list[dict] = []
    seen: set[str] = set()

    for hits in all_hits:
        for hit in filter_hits(hits, threshold=threshold, limit=limit):
            item = hit.get("item") or {}
            item_id = str(item.get("id", ""))

            if not item_id or item_id in seen:
                continue

            seen.add(item_id)
            rows.append(item)

    return [record for record in rebuild_from_items(rows) if isinstance(record, MemoryNote)]


def merge_candidates(*groups: Iterable[MemoryNote]) -> list[MemoryNote]:
    merged: dict[str, MemoryNote] = {}

    for group in groups:
        for note in group:
            merged.setdefault(note.memory_id, note)

    return list(merged.values())
