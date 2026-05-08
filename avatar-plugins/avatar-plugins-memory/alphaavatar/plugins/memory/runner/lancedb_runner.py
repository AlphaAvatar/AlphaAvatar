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

from livekit.agents.inference_runner import _InferenceRunner

from alphaavatar.agents.memory import VectorRunnerOP
from alphaavatar.agents.utils.vdb import embedding, lancedb


class LanceDBRunner(_InferenceRunner):
    INFERENCE_METHOD = "alphaavatar_memory_lancedb"

    def __init__(self):
        super().__init__()

    def _ensure_collection(self, collection_name, embedding_dim) -> None:
        """
        Create table if missing.
        LanceDB does not require pre-declaring vector dim in the same way Qdrant does,
        but we keep this method for interface consistency.
        """
        if self._client.table_exists(collection_name):
            return

        seed = [
            {
                "id": "__init__",
                "vector": [0.0] * embedding_dim,
                "page_content": "__init__",
                "session_id": "",
                "object_id": "",
                "entities": ["__init__"],
                "topic": "",
                "ts": "",
                "memory_type": "",
            }
        ]
        table = self._client.create_table(collection_name, seed)
        table.delete("id = '__init__'")

    def _normalize_entities(self, value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(x) for x in value if x is not None]
        if isinstance(value, tuple):
            return [str(x) for x in value if x is not None]
        return [str(value)]

    def _to_row(self, item: dict, vector: list[float]) -> dict:
        metadata = item.get("metadata", {}) or {}
        return {
            "id": str(item["id"]),
            "vector": vector,
            "page_content": item.get("page_content", ""),
            "session_id": metadata.get("session_id", ""),
            "object_id": metadata.get("object_id", ""),
            "entities": self._normalize_entities(metadata.get("entities")),
            "topic": metadata.get("topic", ""),
            "ts": metadata.get("ts", ""),
            "memory_type": str(metadata.get("memory_type", "")),
        }

    def _row_to_item(self, row: dict) -> dict:
        return {
            "id": str(row.get("id", "")),
            "page_content": row.get("page_content", ""),
            "metadata": {
                "session_id": row.get("session_id", ""),
                "object_id": row.get("object_id", ""),
                "entities": row.get("entities", []),
                "topic": row.get("topic", ""),
                "ts": row.get("ts", ""),
                "memory_type": row.get("memory_type", ""),
            },
        }

    def _search_with_object_id(self, query_vec: list[float], obj_id: str, k: int):
        """
        LanceDB supports vector search, but filtering syntax varies a bit by version.
        We do vector search first, then Python-side filter for maximum compatibility.
        """
        table = self._memory_table
        all_count = table.count_rows()
        if all_count == 0:
            return []

        fetch_k = min(max(k * 8, 32), all_count)

        try:
            rows = table.search(query_vec).limit(fetch_k).to_list()
        except Exception:
            rows = []

        memory_items = []
        for row in rows:
            if str(row.get("object_id", "")) != obj_id:
                continue

            memory_items.append(self._row_to_item(row))
            if len(memory_items) >= k:
                break

        return memory_items

    def _search_by_context(
        self,
        *,
        context_str: str,
        avatar_id: str,
        user_or_tool_id: str | None = None,
        top_k: int = 10,
    ) -> dict:
        out = {
            "memory_items": [],
            "error": None,
        }

        try:
            query_vec = self._embeddings.embed_query(context_str)
            out["memory_items"] = self._search_with_object_id(query_vec, avatar_id, top_k)
            if user_or_tool_id:
                out["memory_items"].extend(
                    self._search_with_object_id(query_vec, user_or_tool_id, top_k)
                )
        except Exception as e:
            out["error"] = str(e)

        return out

    def _save(self, *, memory_items: list[dict]) -> dict:
        result = {
            "deleted_ids": [],
            "inserted": 0,
            "error": None,
        }

        try:
            if not memory_items:
                return result

            ids = [str(it["id"]) for it in memory_items if "id" in it]
            if ids:
                quoted_ids = ",".join(f"'{x}'" for x in ids)
                self._memory_table.delete(f"id IN ({quoted_ids})")
                result["deleted_ids"] = ids

            texts = [it["page_content"] for it in memory_items]
            vectors = self._embeddings.embed_documents(texts)

            rows = [
                self._to_row(item, vector)
                for item, vector in zip(memory_items, vectors, strict=True)
            ]

            self._memory_table.add(rows)
            result["inserted"] = len(rows)

        except Exception as e:
            result["error"] = str(e)

        return result

    def initialize(self) -> None:
        config = os.getenv("MEMORY_VDB_CONFIG", "{}")
        config = json.loads(config)
        self._collection_name = config.get("collection_name", None)

        if not self._collection_name:
            raise ValueError("collection_name is required in MEMORY_VDB_CONFIG")

        self._client = lancedb.get_client(**config)

        self._embeddings = embedding.get_model(**config)
        embedding_dim = len(self._embeddings.embed_query("dimension-probe"))

        self._ensure_collection(self._collection_name, embedding_dim)
        self._memory_table = self._client.open_table(self._collection_name)

    def run(self, data: bytes) -> bytes | None:
        json_data = json.loads(data)

        match json_data["op"]:
            case VectorRunnerOP.search_by_context:
                result = self._search_by_context(**json_data["param"])
                return json.dumps(result).encode()
            case VectorRunnerOP.save:
                result = self._save(**json_data["param"])
                return json.dumps(result).encode()
            case _:
                return None
