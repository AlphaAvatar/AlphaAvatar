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
from typing import Any

from alphaavatar.agents.memory.enums import MemoryKind, MemoryType
from alphaavatar.agents.memory.schemas import (
    MemoryContextRef,
    MemoryItem,
    MemoryOwnerRef,
    MemoryScope,
)

from .database import connect


def placeholders(size: int) -> str:
    return ",".join("?" for _ in range(size))


def normalize_memory_ids(memory_ids: list[str]) -> list[str]:
    return list(
        dict.fromkeys(memory_id for value in memory_ids if (memory_id := str(value).strip()))
    )


def owner_keys(owner_refs: list[MemoryOwnerRef]) -> list[str]:
    return list(dict.fromkeys(ref.key for ref in owner_refs))


def visibility_clause(
    alias: str,
    owner_refs: list[MemoryOwnerRef],
    context: MemoryContextRef,
) -> tuple[str, list[Any]]:
    owners = owner_keys(owner_refs)

    if not owners:
        return "0", []

    scopes = list(MemoryScope.applicable_keys(context))

    sql = (
        f"EXISTS ("
        f"SELECT 1 FROM memory_refs o "
        f"WHERE o.memory_id={alias}.memory_id "
        f"AND o.ref_group='owner' "
        f"AND o.ref_key IN ({placeholders(len(owners))})"
        f") "
        f"AND {alias}.scope_key IN ({placeholders(len(scopes))})"
    )

    return sql, [*owners, *scopes]


def fetch_many(
    connection: sqlite3.Connection,
    memory_ids: list[str],
) -> list[MemoryItem]:
    memory_ids = normalize_memory_ids(memory_ids)

    if not memory_ids:
        return []

    rows = connection.execute(
        f"""
        SELECT memory_id, payload_json
        FROM memory_records
        WHERE memory_id IN ({placeholders(len(memory_ids))})
        """,
        memory_ids,
    ).fetchall()

    by_id = {
        str(row["memory_id"]): MemoryItem.model_validate_json(row["payload_json"]) for row in rows
    }

    return [by_id[memory_id] for memory_id in memory_ids if memory_id in by_id]


def fetch_visible(
    connection: sqlite3.Connection,
    memory_ids: list[str],
    owner_refs: list[MemoryOwnerRef],
    context: MemoryContextRef,
) -> list[MemoryItem]:
    memory_ids = normalize_memory_ids(memory_ids)

    if not memory_ids or not owner_refs:
        return []

    visibility, params = visibility_clause(
        "r",
        owner_refs,
        context,
    )

    rows = connection.execute(
        f"""
        SELECT r.memory_id, r.payload_json
        FROM memory_records r
        WHERE r.memory_id IN ({placeholders(len(memory_ids))})
          AND {visibility}
        """,
        [*memory_ids, *params],
    ).fetchall()

    by_id = {
        str(row["memory_id"]): MemoryItem.model_validate_json(row["payload_json"]) for row in rows
    }

    return [by_id[memory_id] for memory_id in memory_ids if memory_id in by_id]


def get_many_sync(
    path: pathlib.Path,
    memory_ids: list[str],
) -> list[MemoryItem]:
    connection = connect(path)

    try:
        return fetch_many(connection, memory_ids)
    finally:
        connection.close()


def get_visible_sync(
    path: pathlib.Path,
    memory_ids: list[str],
    owner_refs: list[MemoryOwnerRef],
    context: MemoryContextRef,
) -> list[MemoryItem]:
    connection = connect(path)

    try:
        return fetch_visible(
            connection,
            memory_ids,
            owner_refs,
            context,
        )
    finally:
        connection.close()


def query_visible_sync(
    path: pathlib.Path,
    owner_refs: list[MemoryOwnerRef],
    context: MemoryContextRef,
    memory_type: MemoryType | None,
    kind: MemoryKind | None,
    limit: int,
) -> list[MemoryItem]:
    if limit <= 0 or not owner_refs:
        return []

    visibility, params = visibility_clause(
        "r",
        owner_refs,
        context,
    )

    clauses = [visibility]

    if memory_type is not None:
        clauses.append("r.memory_type=?")
        params.append(memory_type.value)

    if kind is not None:
        clauses.append("r.kind=?")
        params.append(kind.value)

    connection = connect(path)

    try:
        rows = connection.execute(
            f"""
            SELECT r.payload_json
            FROM memory_records r
            WHERE {" AND ".join(clauses)}
            ORDER BY
                r.updated_ts DESC,
                r.revision DESC,
                r.memory_id DESC
            LIMIT ?
            """,
            [*params, limit],
        ).fetchall()

        return [MemoryItem.model_validate_json(row["payload_json"]) for row in rows]
    finally:
        connection.close()


def get_checkpoint_sync(
    path: pathlib.Path,
    context_id: str,
    processor: str,
) -> int:
    connection = connect(path)

    try:
        row = connection.execute(
            """
            SELECT sequence
            FROM memory_checkpoints
            WHERE context_id=? AND processor=?
            """,
            (context_id, processor),
        ).fetchone()

        return int(row["sequence"]) if row is not None else 0
    finally:
        connection.close()
