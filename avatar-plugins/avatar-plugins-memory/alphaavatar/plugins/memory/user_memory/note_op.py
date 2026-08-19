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

from datetime import datetime

from alphaavatar.agents.memory import MemoryItem, MemoryNote, MemoryType

from ..memory_op import NOTE_BACKREF_KEY
from .schema import NEW_NOTE_PREFIX, ConsolidationResult, NoteConsolidation

# --------------------------------- Note building ---------------------------------
# Deterministic, free of LLM/VDB access. The model may hallucinate note ids,
# skip items, return nothing, or assign one item twice -- all of it is handled
# here so no single bad response can overwrite a historical memory or lose a fact.


def _with_backref(item: MemoryItem, note_id: str) -> MemoryItem:
    """Attach a note back-reference by building a NEW item.

    Only membership metadata is added. `value`, `topic`, `created_at` and the
    graph payload are untouched: the content of an atomic fact stays immutable.
    The project also forbids in-place mutation, hence the copy.
    """
    return item.model_copy(
        update={"extra_data": {**item.extra_data, NOTE_BACKREF_KEY: note_id}},
        deep=True,
    )


def _merge_item_ids(existing: list[str], added: list[str], *, limit: int) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()

    for item_id in [*existing, *added]:
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        merged.append(item_id)

    # Oldest first, so an over-long note sheds its earliest coverage. Splitting
    # such a note is the real fix and is tracked in the design doc.
    return merged[-limit:]


# A note's key is only as wide as the subjects it advertises. Carrying just
# one member topic leaves most of what the note covers invisible to search,
# which is why they are joined rather than picked.
TOPIC_SEPARATOR = "|"
MAX_TOPIC_PARTS = 8


def merge_topics(*sources: str | None, limit: int = MAX_TOPIC_PARTS) -> str | None:
    """Union of topics, order preserved, joined for a single stored field."""
    parts: list[str] = []
    seen: set[str] = set()

    for source in sources:
        for part in (source or "").split(TOPIC_SEPARATOR):
            part = part.strip()
            if not part or part in seen:
                continue
            seen.add(part)
            parts.append(part)

    if not parts:
        return None

    # Newest last, so an over-full topic drops what it advertised earliest.
    return TOPIC_SEPARATOR.join(parts[-limit:])


def topics_of(items: list[MemoryItem]) -> str | None:
    return merge_topics(*(item.topic for item in items))


def build_note(
    *,
    value: str,
    topic: str | None,
    item_ids: list[str],
    session_id: str,
    object_ids: list[str],
    created_at: datetime,
) -> MemoryNote:
    return MemoryNote(
        # _persist_memory_items only writes records flagged as updated; a note
        # without the flag is silently filtered out and never reaches the VDB.
        updated=True,
        session_id=session_id,
        object_ids=list(object_ids),
        value=value,
        topic=topic,
        created_at=created_at,
        memory_type=MemoryType.CONVERSATION,
        item_ids=list(item_ids),
    )


def rewrite_note(
    original: MemoryNote,
    *,
    value: str,
    topic: str | None,
    added_item_ids: list[str],
    session_id: str,
    updated_at: datetime,
    max_item_ids: int,
) -> MemoryNote:
    """Immutable update of an existing note.

    The original memory_id is kept so the VDB save (delete-by-id + reinsert)
    acts as an upsert, and the original created_at is kept because it records
    when the event was first observed -- overwriting it would corrupt temporal
    reasoning. `session_id` moves to the session that produced this update.
    """
    return MemoryNote(
        updated=True,
        memory_id=original.memory_id,
        session_id=session_id,
        object_ids=list(original.object_ids),
        value=value or original.value,
        topic=merge_topics(original.topic, topic),
        created_at=original.created_at,
        memory_type=original.memory_type,
        item_ids=_merge_item_ids(original.item_ids, added_item_ids, limit=max_item_ids),
        graph_nodes=list(original.graph_nodes),
        graph_links=list(original.graph_links),
        extra_data={
            **original.extra_data,
            "updated_in_session": session_id,
            "updated_at": updated_at.isoformat(),
        },
    )


def _fallback_single_note(
    items: list[MemoryItem],
    *,
    session_id: str,
    object_ids: list[str],
    created_at: datetime,
) -> ConsolidationResult:
    """Degrade to session_summary shape: one note over everything, nothing lost."""
    note = build_note(
        value="\n".join(item.value for item in items if item.value),
        topic=topics_of(items),
        item_ids=[item.memory_id for item in items],
        session_id=session_id,
        object_ids=object_ids,
        created_at=created_at,
    )

    return ConsolidationResult(
        items=[_with_backref(item, note.memory_id) for item in items],
        to_insert=[note],
    )


def apply_assignments(
    consolidation: NoteConsolidation | None,
    *,
    items: list[MemoryItem],
    candidates: list[MemoryNote],
    session_id: str,
    object_ids: list[str],
    created_at: datetime,
    updated_at: datetime,
    max_item_ids: int,
) -> ConsolidationResult:
    """Turn one consolidation response into the records to persist."""
    if not items:
        return ConsolidationResult()

    if consolidation is None or not consolidation.notes:
        return _fallback_single_note(
            items, session_id=session_id, object_ids=object_ids, created_at=created_at
        )

    candidate_by_id = {note.memory_id: note for note in candidates}
    item_by_id = {item.memory_id: item for item in items}

    drafts = {draft.note_id: draft for draft in consolidation.notes if draft.note_id}

    # An assignment is only honoured when the target actually has content to
    # write. Otherwise the item falls back to the leftover bucket.
    assigned: dict[str, list[str]] = {}
    claimed: set[str] = set()

    for assignment in consolidation.assignments:
        item_id = assignment.item_id
        note_id = assignment.note_id

        if item_id not in item_by_id or item_id in claimed:
            continue

        draft = drafts.get(note_id)
        if draft is None or not draft.value.strip():
            continue

        # An id that names neither a retrieved candidate nor a new note is a
        # hallucination. Treating it as new is safe; honouring it would let one
        # bad response overwrite an arbitrary memory.
        if not note_id.startswith(NEW_NOTE_PREFIX) and note_id not in candidate_by_id:
            note_id = f"{NEW_NOTE_PREFIX}{note_id}"
            drafts.setdefault(note_id, draft.model_copy(update={"note_id": note_id}))

        claimed.add(item_id)
        assigned.setdefault(note_id, []).append(item_id)

    leftovers = [item for item in items if item.memory_id not in claimed]

    if not assigned:
        return _fallback_single_note(
            items, session_id=session_id, object_ids=object_ids, created_at=created_at
        )

    result = ConsolidationResult()
    backref_by_item: dict[str, str] = {}

    for note_id, item_ids in assigned.items():
        draft = drafts[note_id]
        original = candidate_by_id.get(note_id)

        if original is not None:
            note = rewrite_note(
                original,
                value=draft.value,
                topic=topics_of([item_by_id[i] for i in item_ids if i in item_by_id]),
                added_item_ids=item_ids,
                session_id=session_id,
                updated_at=updated_at,
                max_item_ids=max_item_ids,
            )
            result.to_rewrite.append(note)
        else:
            note = build_note(
                value=draft.value,
                topic=topics_of([item_by_id[i] for i in item_ids if i in item_by_id]),
                item_ids=item_ids[-max_item_ids:],
                session_id=session_id,
                object_ids=object_ids,
                created_at=created_at,
            )
            result.to_insert.append(note)

        for item_id in note.item_ids:
            backref_by_item[item_id] = note.memory_id

    if leftovers:
        leftover_note = build_note(
            value="\n".join(item.value for item in leftovers if item.value),
            topic=topics_of(leftovers),
            item_ids=[item.memory_id for item in leftovers],
            session_id=session_id,
            object_ids=object_ids,
            created_at=created_at,
        )
        result.to_insert.append(leftover_note)

        for item in leftovers:
            backref_by_item[item.memory_id] = leftover_note.memory_id

    result.items = [
        _with_backref(item, backref_by_item[item.memory_id])
        if item.memory_id in backref_by_item
        else item
        for item in items
    ]

    return result
