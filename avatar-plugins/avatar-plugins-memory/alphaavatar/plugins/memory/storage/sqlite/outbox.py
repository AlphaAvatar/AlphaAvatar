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
import time

from alphaavatar.agents.memory import MemoryStoreConflict
from alphaavatar.agents.memory.enums import MemoryOutboxTarget
from alphaavatar.agents.memory.schemas import MemoryOutboxEvent

from .database import connect
from .query import placeholders


def _event_ids(values: list[int]) -> list[int]:
    return list(dict.fromkeys(int(value) for value in values))


def claim_outbox_sync(
    path: pathlib.Path,
    target: MemoryOutboxTarget,
    worker_id: str,
    limit: int,
    lease_seconds: float,
) -> list[MemoryOutboxEvent]:
    connection = connect(path)

    try:
        connection.execute("BEGIN IMMEDIATE")
        now = time.time()

        rows = connection.execute(
            """
            SELECT event_id
            FROM memory_outbox
            WHERE target=?
              AND available_at<=?
              AND (
                    state='pending'
                    OR (
                        state='processing'
                        AND (
                            lease_until IS NULL
                            OR lease_until<=?
                        )
                    )
              )
            ORDER BY event_id
            LIMIT ?
            """,
            (
                target.value,
                now,
                now,
                limit,
            ),
        ).fetchall()

        event_ids = [int(row["event_id"]) for row in rows]

        if not event_ids:
            connection.commit()
            return []

        lease_until = now + lease_seconds

        connection.executemany(
            """
            UPDATE memory_outbox
            SET
                state='processing',
                attempts=attempts+1,
                lease_owner=?,
                lease_until=?
            WHERE event_id=?
            """,
            [
                (
                    worker_id,
                    lease_until,
                    event_id,
                )
                for event_id in event_ids
            ],
        )

        rows = connection.execute(
            f"""
            SELECT
                event_id,
                target,
                memory_id,
                revision,
                attempts,
                available_at,
                lease_owner,
                lease_until,
                last_error
            FROM memory_outbox
            WHERE event_id IN ({placeholders(len(event_ids))})
            ORDER BY event_id
            """,
            event_ids,
        ).fetchall()

        connection.commit()

        return [MemoryOutboxEvent.model_validate(dict(row)) for row in rows]

    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def complete_outbox_sync(
    path: pathlib.Path,
    event_ids: list[int],
    worker_id: str,
) -> None:
    event_ids = _event_ids(event_ids)

    if not event_ids:
        return

    connection = connect(path)

    try:
        connection.execute("BEGIN IMMEDIATE")

        cursor = connection.execute(
            f"""
            DELETE FROM memory_outbox
            WHERE event_id IN ({placeholders(len(event_ids))})
              AND state='processing'
              AND lease_owner=?
            """,
            [*event_ids, worker_id],
        )

        if cursor.rowcount != len(event_ids):
            raise MemoryStoreConflict("Cannot complete outbox events not owned by this worker")

        connection.commit()

    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def retry_outbox_sync(
    path: pathlib.Path,
    event_id: int,
    worker_id: str,
    error: str,
    delay_seconds: float,
) -> None:
    connection = connect(path)

    try:
        connection.execute("BEGIN IMMEDIATE")

        cursor = connection.execute(
            """
            UPDATE memory_outbox
            SET
                state='pending',
                available_at=?,
                lease_owner=NULL,
                lease_until=NULL,
                last_error=?
            WHERE event_id=?
              AND state='processing'
              AND lease_owner=?
            """,
            (
                time.time() + delay_seconds,
                error,
                event_id,
                worker_id,
            ),
        )

        if cursor.rowcount != 1:
            raise MemoryStoreConflict("Cannot retry outbox event not owned by this worker")

        connection.commit()

    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
