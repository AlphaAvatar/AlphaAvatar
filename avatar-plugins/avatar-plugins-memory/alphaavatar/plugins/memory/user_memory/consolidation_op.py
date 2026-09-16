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
from datetime import datetime
from typing import Protocol, TypeVar

from alphaavatar.agents.memory.enums import MemoryKind
from alphaavatar.agents.memory.schemas import MemoryItem

from .schema import (
    NEW_CONSOLIDATED_PREFIX,
    ConsolidatedMemoryDraft,
    ConsolidationPlan,
    ConsolidationResult,
)


class _KeyedRef(Protocol):
    @property
    def key(self) -> str: ...


TRef = TypeVar("TRef", bound=_KeyedRef)


def _merge_refs(groups: Iterable[Iterable[TRef]]) -> list[TRef]:
    out: list[TRef] = []
    seen: set[str] = set()

    for group in groups:
        for ref in group:
            if ref.key in seen:
                continue
            seen.add(ref.key)
            out.append(ref)

    return out


def _merge_ids(*groups: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for group in groups for value in group if value))


def _owner_keys(item: MemoryItem) -> tuple[str, ...]:
    return tuple(sorted(ref.key for ref in item.owner_refs))


def _merge_topics(*topics: str | None) -> str | None:
    values = list(dict.fromkeys(topic.strip() for topic in topics if topic and topic.strip()))
    return " / ".join(values) if values else None


def _validate_sources(items: list[MemoryItem]) -> MemoryItem:
    if not items:
        raise ValueError("Consolidation requires at least one source memory")

    first = items[0]

    if first.kind is not MemoryKind.ATOMIC:
        raise ValueError("Consolidation sources must be atomic memories")

    owners = _owner_keys(first)

    for item in items[1:]:
        if item.kind is not MemoryKind.ATOMIC:
            raise ValueError("Consolidation sources must be atomic memories")

        if item.memory_type != first.memory_type:
            raise ValueError("Cannot consolidate different memory types")

        if item.context.context_id != first.context.context_id:
            raise ValueError("Cannot consolidate source memories from different contexts")

        if item.scope.key != first.scope.key:
            raise ValueError("Cannot consolidate memories across scopes")

        if _owner_keys(item) != owners:
            raise ValueError("Cannot consolidate memories across owner domains")

    return first


def build_consolidated_memory(
    *,
    draft: ConsolidatedMemoryDraft,
    items: list[MemoryItem],
    resolve_sources: bool,
    created_at: datetime,
) -> MemoryItem:
    first = _validate_sources(items)
    value = draft.value.strip()

    if not value:
        raise ValueError("Consolidated memory value cannot be empty")

    source_ids = [item.memory_id for item in items]

    return MemoryItem(
        kind=MemoryKind.CONSOLIDATED,
        context=first.context,
        scope=first.scope,
        owner_refs=list(first.owner_refs),
        participant_refs=_merge_refs(item.participant_refs for item in items),
        source_refs=_merge_refs(item.source_refs for item in items),
        value=value,
        topic=_merge_topics(*(item.topic for item in items)),
        created_at=created_at,
        updated_at=created_at,
        memory_type=first.memory_type,
        source_memory_ids=source_ids,
        supersedes_memory_ids=source_ids if resolve_sources else [],
    )


def rewrite_consolidated_memory(
    original: MemoryItem,
    *,
    draft: ConsolidatedMemoryDraft,
    added_items: list[MemoryItem],
    resolve_sources: bool,
    updated_at: datetime,
) -> MemoryItem:
    if original.kind is not MemoryKind.CONSOLIDATED:
        raise ValueError(f"Memory {original.memory_id} is not consolidated")

    if added_items:
        first = _validate_sources(added_items)

        if first.memory_type != original.memory_type:
            raise ValueError("Cannot rewrite a consolidated memory with a different memory type")

        if first.scope.key != original.scope.key:
            raise ValueError("Cannot rewrite a consolidated memory across scopes")

        if _owner_keys(first) != _owner_keys(original):
            raise ValueError("Cannot rewrite a consolidated memory across owner domains")

    value = draft.value.strip() or original.value

    source_ids = _merge_ids(
        original.source_memory_ids,
        (item.memory_id for item in added_items),
    )

    supersedes = _merge_ids(
        original.supersedes_memory_ids,
        (item.memory_id for item in added_items) if resolve_sources else (),
    )

    return MemoryItem.model_validate(
        {
            **original.model_dump(),
            "value": value,
            "topic": _merge_topics(
                original.topic,
                *(item.topic for item in added_items),
            ),
            "updated_at": updated_at,
            "revision": original.revision + 1,
            "participant_refs": _merge_refs(
                [
                    original.participant_refs,
                    *(item.participant_refs for item in added_items),
                ]
            ),
            "source_refs": _merge_refs(
                [
                    original.source_refs,
                    *(item.source_refs for item in added_items),
                ]
            ),
            "source_memory_ids": source_ids,
            "supersedes_memory_ids": supersedes,
        }
    )


def apply_assignments(
    items: list[MemoryItem],
    candidates: list[MemoryItem],
    plan: ConsolidationPlan,
    *,
    resolve_sources: bool,
    updated_at: datetime,
) -> ConsolidationResult:
    if not items:
        return ConsolidationResult(
            source_items=[],
            to_insert=[],
            to_rewrite=[],
        )

    incoming = {item.memory_id: item for item in items}
    existing = {item.memory_id: item for item in candidates}

    drafts: dict[str, ConsolidatedMemoryDraft] = {}
    for draft in plan.memories:
        if draft.memory_id in drafts:
            raise ValueError(f"Duplicate consolidated memory draft: {draft.memory_id}")
        drafts[draft.memory_id] = draft

    grouped: dict[str, list[MemoryItem]] = {}
    assigned: dict[str, str] = {}

    for assignment in plan.assignments:
        source_id = assignment.source_memory_id
        target_id = assignment.target_memory_id

        if source_id not in incoming:
            raise ValueError(f"Unknown consolidation source memory: {source_id}")

        previous = assigned.get(source_id)

        if previous is not None:
            if previous != target_id:
                raise ValueError(
                    f"Memory {source_id} is assigned to multiple consolidation targets"
                )
            continue

        assigned[source_id] = target_id
        grouped.setdefault(target_id, []).append(incoming[source_id])

    to_insert: list[MemoryItem] = []
    to_rewrite: list[MemoryItem] = []

    for target_id, source_items in grouped.items():
        draft = drafts.get(target_id)

        if draft is None:
            raise ValueError(f"Missing consolidated memory draft for target: {target_id}")

        if target_id.startswith(NEW_CONSOLIDATED_PREFIX):
            to_insert.append(
                build_consolidated_memory(
                    draft=draft,
                    items=source_items,
                    resolve_sources=resolve_sources,
                    created_at=updated_at,
                )
            )
            continue

        original = existing.get(target_id)

        if original is None:
            raise ValueError(f"Unknown consolidated memory target: {target_id}")

        to_rewrite.append(
            rewrite_consolidated_memory(
                original,
                draft=draft,
                added_items=source_items,
                resolve_sources=resolve_sources,
                updated_at=updated_at,
            )
        )

    return ConsolidationResult(
        source_items=list(items),
        to_insert=to_insert,
        to_rewrite=to_rewrite,
    )
