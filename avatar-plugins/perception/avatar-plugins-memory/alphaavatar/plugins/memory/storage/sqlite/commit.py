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

import hashlib
import json
import pathlib
import time

from alphaavatar.agents.memory import (
    MemoryCheckpointConflict,
    MemoryRevisionConflict,
    MemoryStoreConflict,
)
from alphaavatar.agents.memory.enums import MemoryOutboxTarget
from alphaavatar.agents.memory.schemas import (
    MemoryCheckpointAdvance,
    MemoryCommitResult,
    MemoryItem,
)

from .database import connect


def build_request_hash(
    items: list[MemoryItem],
    *,
    context_id: str,
    processor: str,
    checkpoint: MemoryCheckpointAdvance | None,
) -> str:
    payload = {
        "context_id": context_id,
        "processor": processor,
        "checkpoint": checkpoint.model_dump(mode="json") if checkpoint else None,
        "items": [
            item.model_dump(mode="json") for item in sorted(items, key=lambda item: item.memory_id)
        ],
    }

    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()

    return hashlib.sha256(raw).hexdigest()


def commit_sync(
    path: pathlib.Path,
    items: list[MemoryItem],
    context_id: str,
    processor: str,
    idempotency_key: str,
    checkpoint: MemoryCheckpointAdvance | None,
) -> MemoryCommitResult:
    request_hash = build_request_hash(
        items,
        context_id=context_id,
        processor=processor,
        checkpoint=checkpoint,
    )

    connection = connect(path)

    try:
        connection.execute("BEGIN IMMEDIATE")

        previous = connection.execute(
            """
            SELECT request_hash, context_id, processor, result_json
            FROM memory_commits
            WHERE idempotency_key=?
            """,
            (idempotency_key,),
        ).fetchone()

        if previous is not None:
            if (
                previous["request_hash"] != request_hash
                or previous["context_id"] != context_id
                or previous["processor"] != processor
            ):
                raise MemoryStoreConflict(
                    f"Idempotency key {idempotency_key!r} was reused with a different memory commit"
                )

            result = MemoryCommitResult.model_validate_json(previous["result_json"])

            connection.commit()

            return MemoryCommitResult.model_validate(
                {
                    **result.model_dump(),
                    "duplicate": True,
                }
            )

        if checkpoint is not None:
            row = connection.execute(
                """
                SELECT sequence
                FROM memory_checkpoints
                WHERE context_id=? AND processor=?
                """,
                (context_id, processor),
            ).fetchone()

            current = int(row["sequence"]) if row is not None else 0

            if current != checkpoint.from_sequence:
                raise MemoryCheckpointConflict(
                    f"Checkpoint {context_id}:{processor} expected "
                    f"{checkpoint.from_sequence}, current {current}"
                )

        memory_ids = [item.memory_id for item in items]

        if len(memory_ids) != len(set(memory_ids)):
            raise ValueError("Memory commit contains duplicate memory_ids")

        # Write records first so relations inside the same transaction can
        # reference newly inserted MemoryItems.
        for item in items:
            row = connection.execute(
                """
                SELECT revision
                FROM memory_records
                WHERE memory_id=?
                """,
                (item.memory_id,),
            ).fetchone()

            if row is None:
                if item.revision != 1:
                    raise MemoryRevisionConflict(
                        f"New memory {item.memory_id} must start at revision 1"
                    )
            else:
                expected = int(row["revision"]) + 1

                if item.revision != expected:
                    raise MemoryRevisionConflict(
                        f"Memory {item.memory_id} expected revision {expected}, got {item.revision}"
                    )

            updated_at = item.updated_at or item.created_at

            connection.execute(
                """
                INSERT INTO memory_records(
                    memory_id,
                    kind,
                    memory_type,
                    episode_id,
                    context_id,
                    runtime_session_id,
                    parent_context_id,
                    task_id,
                    scope_key,
                    value,
                    topic,
                    created_at,
                    updated_at,
                    updated_ts,
                    revision,
                    payload_json
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    kind=excluded.kind,
                    memory_type=excluded.memory_type,
                    episode_id=excluded.episode_id,
                    context_id=excluded.context_id,
                    runtime_session_id=excluded.runtime_session_id,
                    parent_context_id=excluded.parent_context_id,
                    task_id=excluded.task_id,
                    scope_key=excluded.scope_key,
                    value=excluded.value,
                    topic=excluded.topic,
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at,
                    updated_ts=excluded.updated_ts,
                    revision=excluded.revision,
                    payload_json=excluded.payload_json
                """,
                (
                    item.memory_id,
                    item.kind.value,
                    item.memory_type.value,
                    item.context.episode_id,
                    item.context.context_id,
                    item.context.session_id,
                    item.context.parent_context_id,
                    item.context.task_id,
                    item.scope.key,
                    item.value,
                    item.topic,
                    item.created_at.isoformat(),
                    updated_at.isoformat(),
                    updated_at.timestamp(),
                    item.revision,
                    item.model_dump_json(),
                ),
            )

        now = time.time()

        for item in items:
            connection.execute(
                "DELETE FROM memory_refs WHERE memory_id=?",
                (item.memory_id,),
            )

            refs = [
                *[
                    (
                        item.memory_id,
                        "owner",
                        ref.key,
                        ref.model_dump_json(),
                    )
                    for ref in item.owner_refs
                ],
                *[
                    (
                        item.memory_id,
                        "participant",
                        ref.key,
                        ref.model_dump_json(),
                    )
                    for ref in item.participant_refs
                ],
                *[
                    (
                        item.memory_id,
                        "source",
                        ref.key,
                        ref.model_dump_json(),
                    )
                    for ref in item.source_refs
                ],
            ]

            if refs:
                connection.executemany(
                    """
                    INSERT INTO memory_refs(
                        memory_id,
                        ref_group,
                        ref_key,
                        payload_json
                    )
                    VALUES(?,?,?,?)
                    """,
                    refs,
                )

            connection.execute(
                "DELETE FROM memory_relations WHERE memory_id=?",
                (item.memory_id,),
            )

            relations = [
                *[
                    (
                        item.memory_id,
                        "source",
                        source_id,
                    )
                    for source_id in item.source_memory_ids
                ],
                *[
                    (
                        item.memory_id,
                        "supersedes",
                        source_id,
                    )
                    for source_id in item.supersedes_memory_ids
                ],
            ]

            if relations:
                connection.executemany(
                    """
                    INSERT INTO memory_relations(
                        memory_id,
                        relation_kind,
                        related_memory_id
                    )
                    VALUES(?,?,?)
                    """,
                    relations,
                )

            for target in MemoryOutboxTarget:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO memory_outbox(
                        event_key,
                        target,
                        memory_id,
                        revision,
                        available_at
                    )
                    VALUES(?,?,?,?,?)
                    """,
                    (
                        f"{target.value}:{item.memory_id}:{item.revision}",
                        target.value,
                        item.memory_id,
                        item.revision,
                        now,
                    ),
                )

        checkpoint_sequence = None

        if checkpoint is not None:
            checkpoint_sequence = checkpoint.to_sequence

            connection.execute(
                """
                INSERT INTO memory_checkpoints(
                    context_id,
                    processor,
                    sequence,
                    updated_at
                )
                VALUES(?,?,?,?)
                ON CONFLICT(context_id, processor) DO UPDATE SET
                    sequence=excluded.sequence,
                    updated_at=excluded.updated_at
                """,
                (
                    context_id,
                    processor,
                    checkpoint.to_sequence,
                    now,
                ),
            )

        result = MemoryCommitResult(
            committed=True,
            duplicate=False,
            memory_ids=memory_ids,
            checkpoint_sequence=checkpoint_sequence,
        )

        connection.execute(
            """
            INSERT INTO memory_commits(
                idempotency_key,
                request_hash,
                context_id,
                processor,
                result_json,
                committed_at
            )
            VALUES(?,?,?,?,?,?)
            """,
            (
                idempotency_key,
                request_hash,
                context_id,
                processor,
                result.model_dump_json(),
                now,
            ),
        )

        connection.commit()
        return result

    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
