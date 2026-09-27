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
import pathlib


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

    def drop_table(self, table_name: str) -> None:
        if self.table_exists(table_name):
            self._db.drop_table(table_name)

    def create_or_overwrite_table(self, table_name: str, data: list[dict]):
        if self.table_exists(table_name):
            self.drop_table(table_name)
        return self._db.create_table(table_name, data=data)


def get_client(
    *,
    client_path: str | pathlib.Path,
    **kwargs,
) -> LanceDBClient:
    if not str(client_path).strip():
        raise ValueError("LanceDB client_path cannot be empty")
    return LanceDBClient(path=client_path)
