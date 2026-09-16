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

from .schema import SCHEMA_SQL, SCHEMA_VERSION


def connect(path: pathlib.Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=5.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def initialize_database(path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(path)

    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")

        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        has_records = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memory_records'"
        ).fetchone()

        if version not in (0, SCHEMA_VERSION) or (
            has_records is not None and version != SCHEMA_VERSION
        ):
            raise RuntimeError(
                f"Incompatible MemoryStore schema version={version}; "
                f"expected {SCHEMA_VERSION}. Recreate {path}."
            )

        connection.executescript(SCHEMA_SQL)
        connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    finally:
        connection.close()
