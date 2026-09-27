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
import sqlite3

from alphaavatar.agents.memory import MemoryStoreConflict
from alphaavatar.agents.memory.schemas import (
    MemoryContextRef,
    MemoryItem,
    MemoryOwnerRef,
)

from .database import connect
from .query import (
    fetch_visible,
    normalize_memory_ids,
    placeholders,
    visibility_clause,
)


def _latest_superseders(
    connection: sqlite3.Connection,
    memory_ids: list[str],
    owner_refs: list[MemoryOwnerRef],
    context: MemoryContextRef,
) -> dict[str, MemoryItem]:
    memory_ids = normalize_memory_ids(memory_ids)

    if not memory_ids or not owner_refs:
        return {}

    visibility, params = visibility_clause(
        "r",
        owner_refs,
        context,
    )

    rows = connection.execute(
        f"""
        SELECT
            rel.related_memory_id AS source_id,
            r.memory_id,
            r.payload_json
        FROM memory_relations rel
        JOIN memory_records r
          ON r.memory_id=rel.memory_id
        WHERE rel.relation_kind='supersedes'
          AND rel.related_memory_id
              IN ({placeholders(len(memory_ids))})
          AND {visibility}
        ORDER BY
            rel.related_memory_id,
            r.updated_ts DESC,
            r.revision DESC,
            r.memory_id DESC
        """,
        [*memory_ids, *params],
    ).fetchall()

    out: dict[str, MemoryItem] = {}

    for row in rows:
        source_id = str(row["source_id"])

        if source_id not in out:
            out[source_id] = MemoryItem.model_validate_json(row["payload_json"])

    return out


def resolve_current_sync(
    path: pathlib.Path,
    memory_ids: list[str],
    owner_refs: list[MemoryOwnerRef],
    context: MemoryContextRef,
) -> list[MemoryItem]:
    memory_ids = normalize_memory_ids(memory_ids)

    if not memory_ids or not owner_refs:
        return []

    connection = connect(path)

    try:
        # A WAL read transaction gives Resolution one consistent authoritative
        # snapshot without blocking concurrent writers.
        connection.execute("BEGIN")

        base = fetch_visible(
            connection,
            memory_ids,
            owner_refs,
            context,
        )

        current = {item.memory_id: item for item in base}

        requested = [memory_id for memory_id in memory_ids if memory_id in current]

        resolved = {memory_id: current[memory_id] for memory_id in requested}

        seen = {memory_id: {memory_id} for memory_id in requested}

        while resolved:
            replacements = _latest_superseders(
                connection,
                list(dict.fromkeys(item.memory_id for item in resolved.values())),
                owner_refs,
                context,
            )

            changed = False

            for requested_id, item in list(resolved.items()):
                replacement = replacements.get(item.memory_id)

                if replacement is None:
                    continue

                if replacement.memory_id in seen[requested_id]:
                    raise MemoryStoreConflict(
                        f"Memory supersession cycle detected for {requested_id}"
                    )

                seen[requested_id].add(replacement.memory_id)
                resolved[requested_id] = replacement
                changed = True

            if not changed:
                break

        out: list[MemoryItem] = []
        emitted: set[str] = set()

        for memory_id in requested:
            item = resolved[memory_id]

            if item.memory_id in emitted:
                continue

            emitted.add(item.memory_id)
            out.append(item)

        connection.commit()
        return out

    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
