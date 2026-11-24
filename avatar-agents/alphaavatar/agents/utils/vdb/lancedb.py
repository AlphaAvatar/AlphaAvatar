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
import json
import os
import pathlib
import secrets

from .space import EmbeddingSpace, EmbeddingSpaceError, claim, is_any_record, not_a_record


class LanceDBClient:
    def __init__(self, *, path: str):
        try:
            import lancedb
        except ImportError as e:
            raise ImportError(
                "LanceDB is not installed. Please install it with `pip install lancedb`."
            ) from e

        self.path = pathlib.Path(path).expanduser()
        self.path.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(str(self.path))

    def table_exists(self, table_name: str) -> bool:
        try:
            return table_name in self._db.table_names()
        except Exception:
            return False

    def open_table(self, table_name: str):
        return self._db.open_table(table_name)

    def create_table(self, table_name: str, data: list[dict]):
        if self.table_exists(table_name):
            return self.open_table(table_name)
        return self._db.create_table(table_name, data=data)

    def claim_space(self, table_name: str, space: EmbeddingSpace, *, setting: str, ensure) -> None:
        """Open ``table_name`` for vectors of ``space``, as ``space.claim`` checks and records
        it: the record a JSON file beside the table, read without LanceDB, made whole beside it
        and linked into place, so of Hosts recording at once only the first does. Placed once
        and never taken back, it is decided as placed."""
        record = self.path / f"{table_name}.embedding.json"
        label = f"LanceDB table {table_name!r} in {self.path}"

        def records() -> list[dict]:
            if not record.exists() and not record.is_symlink():
                return []
            try:
                found = json.loads(record.read_text("utf-8"))
            except (OSError, ValueError):
                found = None
            if not is_any_record(found, store=table_name):
                raise EmbeddingSpaceError(not_a_record(str(record), label))
            return [found]

        def register(found: dict) -> None:
            staged = record.with_name(f".{record.name}.{secrets.token_hex(8)}.tmp")
            try:
                with staged.open("x", encoding="utf-8") as stream:
                    stream.write(json.dumps(found, indent=1) + "\n")
                try:
                    os.link(staged, record)
                except FileExistsError:
                    pass  # Another Host recorded first: what it recorded decides.
                except OSError:
                    # No links on this file system: made only where none is, written in place.
                    try:
                        with record.open("x", encoding="utf-8") as stream:
                            stream.write(json.dumps(found, indent=1) + "\n")
                    except FileExistsError:
                        pass
            finally:
                staged.unlink(missing_ok=True)

        def size() -> int | None:
            field = self.open_table(table_name).schema.field("vector")
            return getattr(field.type, "list_size", None)

        claim(
            table_name,
            space,
            label=label,
            setting=setting,
            exists=lambda: self.table_exists(table_name),
            size=size,
            count=lambda: self.open_table(table_name).count_rows(),
            records=records,
            register=register,
            confirm=lambda found: None,  # Decided as placed.
            withdraw=lambda found: None,  # Placed only where none was: kept, never another's.
            ensure=ensure,
        )

    def drop_table(self, table_name: str) -> None:
        if self.table_exists(table_name):
            self._db.drop_table(table_name)

    def create_or_overwrite_table(self, table_name: str, data: list[dict]):
        if self.table_exists(table_name):
            self.drop_table(table_name)
        return self._db.create_table(table_name, data=data)


def get_client(*, client_path: str | pathlib.Path, **kwargs) -> LanceDBClient:
    if not str(client_path).strip():
        raise ValueError("LanceDB client_path cannot be empty")
    return LanceDBClient(path=client_path)
