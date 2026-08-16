# Copyright 2025 AlphaAvatar project
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
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from alphaavatar.agents.memory import MemoryItem, MemoryNote
from alphaavatar.agents.memory.schema.graph import (
    GraphNodeMention,
    MemoryGraphLink,
    MemoryGraphNode,
)


class PatchOp(BaseModel):
    value: str = Field(
        default="",
        description=(
            "Clean human-readable memory text. Do not include structured fields "
            "such as kind/topic/type/who/evidence/metadata."
        ),
    )

    topic: str | None = Field(
        default=None,
        description="Stable short topic label for retrieval and grouping.",
    )

    node_mentions: list[GraphNodeMention] = Field(
        default_factory=list,
        description=(
            "Lightweight graph anchors mentioned in this memory. "
            "Do not include embeddings, graph_nodes, graph_links, aliases, or evidence."
        ),
    )


class MemoryDelta(BaseModel):
    user_or_tool_memory_entries: list[PatchOp] = Field(
        default_factory=list,
        description="A list of memory contents where the Assistant interacts with the user based on the conversation content.",
    )
    assistant_memory_entries: list[PatchOp] = Field(
        default_factory=list,
        description="The Assistant's own memory list is generated based on the conversation content and the memory content list of the Assistant's interaction with the user.",
    )


class EnvMemoryDelta(BaseModel):
    env_memory_entries: list[PatchOp] = Field(
        default_factory=list,
        description="The Assistant's own memory list is generated based on the conversation content and the memory content list of the Assistant's interaction with the user.",
    )


def norm_token(s: Any) -> str:
    """Normalize for case/whitespace-insensitive equality."""
    return " ".join(str(s).strip().lower().split())


def norm_topic(value: str | None) -> str | None:
    if not value:
        return None

    value = " ".join(value.strip().split())
    return value.lower()[:64]


def merge_object_ids(*values: Any) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()

    for value in values:
        if value is None:
            continue

        items = value if isinstance(value, list) else [value]

        for item in items:
            normalized = str(item).strip()

            if not normalized or normalized in seen:
                continue

            seen.add(normalized)
            merged.append(normalized)

    return merged


# doc_kind separates memory rows from graph-node rows in the VDB table.
# Notes are MemoryItems and MUST keep this value, otherwise _search_rows
# (which filters doc_kind == "memory_item") would never return them.
DOC_KIND_MEMORY = "memory_item"

# The item and note layers share one table and one doc_kind. They are told
# apart by two reserved keys inside metadata.extra_data -- NOT by table
# columns: _ensure_collection freezes the schema by inserting and deleting a
# seed row with hard-coded column names, so adding a column would make
# existing tables unreadable.
NOTE_PAYLOAD_KEY = "_note"  # note rows only: {"item_ids": [...]}
NOTE_BACKREF_KEY = "_note_id"  # absorbed item rows only: the note's memory_id

LAYER_ITEM = "item"
LAYER_NOTE = "note"


def row_layer(extra_data: dict[str, Any] | None) -> str:
    """Which layer a stored record belongs to, from its extra_data payload."""
    return LAYER_NOTE if NOTE_PAYLOAD_KEY in (extra_data or {}) else LAYER_ITEM


def flatten_records(
    records: list[MemoryItem],
    *,
    include_topic: bool = False,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    for memory in records:
        extra_data = dict(memory.extra_data or {})

        if isinstance(memory, MemoryNote):
            extra_data[NOTE_PAYLOAD_KEY] = {"item_ids": list(memory.item_ids)}

        items.append(
            {
                "id": memory.memory_id,
                "doc_kind": DOC_KIND_MEMORY,
                "page_content": memory.value,
                "embedding_text": memory.embedding_text(include_topic=include_topic),
                "metadata": {
                    "session_id": memory.session_id,
                    "object_ids": memory.object_ids,
                    "topic": memory.topic,
                    "ts": memory.timestamp,
                    "memory_type": (
                        memory.memory_type.value
                        if hasattr(memory.memory_type, "value")
                        else str(memory.memory_type)
                    ),
                    "graph_nodes": [x.model_dump(mode="json") for x in memory.graph_nodes],
                    "graph_links": [x.model_dump(mode="json") for x in memory.graph_links],
                    "extra_data": extra_data,
                },
            }
        )

    return items


def rebuild_from_items(items: list[dict[str, Any]]) -> list[MemoryItem]:
    out: list[MemoryItem] = []

    for it in items:
        mid = it.get("id", None)
        value = it.get("page_content", None)
        meta = it.get("metadata", {}) or {}

        if mid is None or value is None:
            continue

        extra_data = dict(meta.get("extra_data") or {})
        note_payload = extra_data.pop(NOTE_PAYLOAD_KEY, None)

        common: dict[str, Any] = {
            "memory_id": mid,
            "value": value,
            "session_id": meta.get("session_id"),
            "object_ids": meta.get("object_ids") or [],
            "topic": meta.get("topic"),
            "timestamp": meta.get("ts"),
            "memory_type": meta.get("memory_type"),
            "graph_nodes": [
                MemoryGraphNode.model_validate(x) for x in meta.get("graph_nodes") or []
            ],
            "graph_links": [
                MemoryGraphLink.model_validate(x) for x in meta.get("graph_links") or []
            ],
            "extra_data": extra_data,
        }

        if isinstance(note_payload, dict):
            # Notes written before the layering change carried summary/facts
            # instead of item_ids. They stay readable and updatable; they just
            # cover no items, so nothing resolves onto them.
            out.append(MemoryNote(**common, item_ids=list(note_payload.get("item_ids") or [])))
        else:
            out.append(MemoryItem(**common))

    return out


def _covered_item_ids(rows: list[dict[str, Any]]) -> tuple[set[str], dict[str, str]]:
    """Split rows into (ids covered by a note present here, item -> note backref)."""
    covered: set[str] = set()
    backrefs: dict[str, str] = {}

    for row in rows:
        extra_data = _row_extra_data(row)

        payload = extra_data.get(NOTE_PAYLOAD_KEY)
        if isinstance(payload, dict):
            covered.update(str(x) for x in payload.get("item_ids") or [])
            continue

        backref = extra_data.get(NOTE_BACKREF_KEY)
        if backref:
            backrefs[str(row.get("id"))] = str(backref)

    return covered, backrefs


def _row_extra_data(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata") or {}
    extra_data = metadata.get("extra_data") or {}
    return extra_data if isinstance(extra_data, dict) else {}


def resolve_value_to_note(
    rows: list[dict[str, Any]],
    *,
    fetch_notes: Callable[[list[str]], list[dict[str, Any]]] | None = None,
    max_fetch: int = 0,
) -> list[dict[str, Any]]:
    """Let a note supply the V of every atomic item it has absorbed.

    K/V separation: both layers stay searchable (an item's atomic wording is
    often the better retrieval handle), but the prompt-facing value of an
    absorbed item comes from its note -- the reconciled version. Without this,
    an item that a later note corrected would be re-injected alongside the
    correction, which is exactly the contradiction the note exists to resolve.

    Nothing stored is deleted or modified; this is pure render-time resolution.
    Rows keep their relative order, and each note appears at most once.

    `fetch_notes` resolves notes that were not co-retrieved, via the
    `_note_id` back-reference. It is capped by `max_fetch`; pass no fetcher to
    only collapse notes already present in `rows`.
    """
    covered, backrefs = _covered_item_ids(rows)

    if fetch_notes is not None and max_fetch > 0:
        present = {str(row.get("id")) for row in rows}
        missing: list[str] = []

        for item_id, note_id in backrefs.items():
            if item_id in covered or note_id in present or note_id in missing:
                continue
            missing.append(note_id)
            if len(missing) >= max_fetch:
                break

        if missing:
            fetched = fetch_notes(missing)
            rows = [*rows, *fetched]
            covered, _ = _covered_item_ids(rows)

    resolved: list[dict[str, Any]] = []
    by_id = {str(row.get("id")): row for row in rows}
    seen: set[str] = set()

    for row in rows:
        row_id = str(row.get("id"))

        if row_id in covered:
            note_id = backrefs.get(row_id)
            note_row = by_id.get(note_id) if note_id else None

            if note_row is not None:
                row_id, row = note_id or row_id, note_row
            else:
                # Covered by a note in this batch whose id we cannot name (the
                # item predates back-references). Drop it: the note is present
                # and already carries the reconciled content.
                continue

        if row_id in seen:
            continue

        seen.add(row_id)
        resolved.append(row)

    return resolved
