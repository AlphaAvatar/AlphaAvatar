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
from typing import Any

from livekit.agents.inference_runner import _InferenceRunner

from alphaavatar.agents.memory import VectorRunnerOP
from alphaavatar.agents.providers import ProviderKind, ProviderTaskConfig
from alphaavatar.agents.providers.embedding import create_embedding_model
from alphaavatar.agents.utils.vdb import lancedb


class LanceDBRunner(_InferenceRunner):
    INFERENCE_METHOD = "alphaavatar_memory_lancedb"

    def __init__(self):
        super().__init__()

    """Helper Op"""

    def _as_str_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            values = value
        elif isinstance(value, tuple):
            values = list(value)
        else:
            values = [value]

        out: list[str] = []
        seen: set[str] = set()

        for x in values:
            s = str(x).strip()
            if not s or s in seen:
                continue
            seen.add(s)
            out.append(s)

        return out

    def _json_dumps(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)

    def _json_loads(self, value: Any, fallback: Any):
        if value is None:
            return fallback
        if isinstance(value, dict | list):
            return value
        try:
            return json.loads(value)
        except Exception:
            return fallback

    def _row_matches_object_ids(self, row: dict, object_ids: list[str] | None) -> bool:
        wanted = set(self._as_str_list(object_ids))
        if not wanted:
            return True

        row_object_ids = self._json_loads(row.get("object_ids_json"), [])
        row_set = set(self._as_str_list(row_object_ids))

        return bool(wanted & row_set)

    def _row_matches_filters(
        self,
        row: dict,
        *,
        doc_kind: str | None = None,
        object_ids: list[str] | None = None,
        memory_type: str | None = None,
        session_id: str | None = None,
        node_type: str | None = None,
        node_key: str | None = None,
    ) -> bool:
        if doc_kind and str(row.get("doc_kind", "")) != doc_kind:
            return False
        if node_key and str(row.get("node_key", "")) != node_key:
            return False
        if node_type and str(row.get("node_type", "")) != node_type:
            return False
        if memory_type and str(row.get("memory_type", "")) != memory_type:
            return False
        if session_id and str(row.get("session_id", "")) != session_id:
            return False
        if not self._row_matches_object_ids(row, object_ids):
            return False

        return True

    """VDB Op"""

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
                # memory item fields
                "doc_kind": "memory_item",
                "session_id": "",
                "object_ids_json": "[]",
                "topic": "",
                "ts": "",
                "memory_type": "",
                # graph fields
                "memory_id": "",
                "node_id": "",
                "node_key": "",
                "node_type": "",
                "node_weight": 0.0,
                # json fields
                "graph_nodes_json": "[]",
                "graph_links_json": "[]",
                "extra_data_json": "{}",
            }
        ]
        table = self._client.create_table(collection_name, seed)
        table.delete("id = '__init__'")

    def _to_memory_row(self, item: dict, vector: list[float]) -> dict:
        metadata = item.get("metadata", {}) or {}

        return {
            "id": str(item["id"]),
            "vector": vector,
            "page_content": item.get("page_content", ""),
            "doc_kind": "memory_item",
            "session_id": metadata.get("session_id", ""),
            "object_ids_json": self._json_dumps(metadata.get("object_ids") or []),
            "topic": metadata.get("topic", ""),
            "ts": metadata.get("ts", ""),
            "memory_type": str(metadata.get("memory_type", "")),
            "memory_id": str(item["id"]),
            "node_id": "",
            "node_key": "",
            "node_type": "",
            "node_weight": 0.0,
            "graph_nodes_json": self._json_dumps(metadata.get("graph_nodes") or []),
            "graph_links_json": self._json_dumps(metadata.get("graph_links") or []),
            "extra_data_json": self._json_dumps(metadata.get("extra_data") or {}),
        }

    def _to_graph_node_rows(self, item: dict, vectors: list[list[float]]) -> list[dict]:
        metadata = item.get("metadata", {}) or {}
        memory_id = str(item["id"])

        graph_nodes = metadata.get("graph_nodes") or []
        rows: list[dict] = []

        vector_idx = 0
        for node in graph_nodes:
            extra_data = node.get("extra_data") or {}

            # memory_item node already has a memory item row; skip it to avoid duplicate retrieval.
            if extra_data.get("node_kind") == "memory_item":
                continue

            node_content = str(node.get("content", "")).strip()
            if not node_content:
                continue

            node_key = str(node.get("key", "") or node.get("id", ""))
            node_id = str(node.get("id", ""))
            node_type = str(node.get("type", "text"))
            node_weight = float(node.get("weight", 1.0))

            # occurrence-level id: same graph node can appear in multiple memory items
            row_id = f"graph_node::{memory_id}::{node_key}"

            rows.append(
                {
                    "id": row_id,
                    "vector": vectors[vector_idx],
                    "page_content": node_content,
                    "doc_kind": "graph_node",
                    "session_id": metadata.get("session_id", ""),
                    "object_ids_json": self._json_dumps(metadata.get("object_ids") or []),
                    "topic": metadata.get("topic", ""),
                    "ts": metadata.get("ts", ""),
                    "memory_type": str(metadata.get("memory_type", "")),
                    "memory_id": memory_id,
                    "node_id": node_id,
                    "node_key": node_key,
                    "node_type": node_type,
                    "node_weight": node_weight,
                    "graph_nodes_json": "[]",
                    "graph_links_json": "[]",
                    "extra_data_json": self._json_dumps(extra_data),
                }
            )
            vector_idx += 1

        return rows

    def _row_to_item(self, row: dict) -> dict:
        return {
            "id": str(row.get("id", "")),
            "page_content": row.get("page_content", ""),
            "metadata": {
                "session_id": row.get("session_id", ""),
                "object_ids": self._json_loads(row.get("object_ids_json"), []),
                "topic": row.get("topic", ""),
                "ts": row.get("ts", ""),
                "memory_type": row.get("memory_type", ""),
                "graph_nodes": self._json_loads(row.get("graph_nodes_json"), []),
                "graph_links": self._json_loads(row.get("graph_links_json"), []),
                "extra_data": self._json_loads(row.get("extra_data_json"), {}),
            },
        }

    def _get_memory_items_by_ids(self, memory_ids: list[str]) -> list[dict]:
        if not memory_ids:
            return []

        ordered_ids = [str(x) for x in memory_ids if x]
        target_ids = set(ordered_ids)

        if not target_ids:
            return []

        try:
            rows = self._memory_table.to_list()
        except Exception:
            return []

        item_by_id: dict[str, dict] = {}

        for row in rows:
            if str(row.get("doc_kind", "")) != "memory_item":
                continue

            row_id = str(row.get("id", ""))
            if row_id not in target_ids:
                continue

            item_by_id[row_id] = self._row_to_item(row)

        return [item_by_id[mid] for mid in ordered_ids if mid in item_by_id]

    def _find_memory_ids_by_node_keys(
        self,
        *,
        node_keys: list[str],
        top_k: int,
        memory_type: str | None = None,
        session_id: str | None = None,
        object_ids: list[str] | None = None,
        node_type: str | None = None,
    ) -> list[str]:
        keys = {str(x).strip() for x in node_keys if str(x).strip()}
        if not keys:
            return []

        rows = self._memory_table.to_list()

        out: list[str] = []
        seen: set[str] = set()

        for row in rows:
            if str(row.get("doc_kind", "")) != "graph_node":
                continue
            if str(row.get("node_key", "")) not in keys:
                continue
            if node_type and str(row.get("node_type", "")) != node_type:
                continue
            if memory_type and str(row.get("memory_type", "")) != memory_type:
                continue
            if session_id and str(row.get("session_id", "")) != session_id:
                continue
            if not self._row_matches_object_ids(row, object_ids):
                continue

            memory_id = str(row.get("memory_id", ""))
            if not memory_id or memory_id in seen:
                continue

            seen.add(memory_id)
            out.append(memory_id)

            if len(out) >= top_k:
                break

        return out

    def _find_memory_ids_by_node_query(
        self,
        *,
        node_query: str,
        top_k: int,
        memory_type: str | None = None,
        session_id: str | None = None,
        object_ids: list[str] | None = None,
        node_type: str | None = None,
    ) -> list[str]:
        query_vec = self._embeddings.embed_query(node_query)

        all_count = self._memory_table.count_rows()
        if all_count == 0:
            return []

        fetch_k = min(max(top_k * 16, 64), all_count)

        try:
            rows = self._memory_table.search(query_vec).limit(fetch_k).to_list()
        except Exception:
            rows = []

        out: list[str] = []
        seen: set[str] = set()

        for row in rows:
            if not self._row_matches_filters(
                row,
                doc_kind="graph_node",
                node_type=node_type,
                memory_type=memory_type,
                session_id=session_id,
                object_ids=object_ids,
            ):
                continue

            memory_id = str(row.get("memory_id", ""))
            if not memory_id or memory_id in seen:
                continue

            seen.add(memory_id)
            out.append(memory_id)

            if len(out) >= top_k:
                break

        return out

    """Runner Op"""

    def _search_rows(
        self,
        query_vec: list[float],
        *,
        object_ids: list[str] | None,
        doc_kind: str,
        k: int,
    ):
        table = self._memory_table
        all_count = table.count_rows()
        if all_count == 0:
            return []

        fetch_k = min(max(k * 12, 48), all_count)

        try:
            rows = table.search(query_vec).limit(fetch_k).to_list()
        except Exception:
            rows = []

        out = []
        for row in rows:
            if not self._row_matches_filters(
                row,
                doc_kind=doc_kind,
                object_ids=object_ids,
            ):
                continue

            out.append(row)
            if len(out) >= k:
                break

        return out

    def _search_by_context(
        self,
        *,
        context_str: str,
        object_ids: list[str] | None = None,
        top_k: int = 10,
    ) -> dict:
        out = {
            "memory_items": [],
            "error": None,
        }

        try:
            query_vec = self._embeddings.embed_query(context_str)

            memory_rows = self._search_rows(
                query_vec,
                object_ids=object_ids,
                doc_kind="memory_item",
                k=top_k,
            )

            graph_rows = self._search_rows(
                query_vec,
                object_ids=object_ids,
                doc_kind="graph_node",
                k=top_k,
            )

            merged: dict[str, dict] = {}

            for row in memory_rows:
                item = self._row_to_item(row)
                merged[item["id"]] = item

            graph_memory_ids = [
                str(row.get("memory_id", "")) for row in graph_rows if row.get("memory_id")
            ]

            for item in self._get_memory_items_by_ids(graph_memory_ids):
                merged[item["id"]] = item

            out["memory_items"] = list(merged.values())[:top_k]

        except Exception as e:
            out["error"] = str(e)

        return out

    def _search_by_graph_node(
        self,
        *,
        node_key: str | None = None,
        node_keys: list[str] | None = None,
        node_query: str | None = None,
        top_k: int = 50,
        memory_type: str | None = None,
        session_id: str | None = None,
        object_ids: list[str] | None = None,
        node_type: str | None = None,
    ) -> dict:
        out = {
            "memory_items": [],
            "error": None,
        }

        try:
            memory_ids: list[str] = []

            exact_keys: list[str] = []
            if node_key:
                exact_keys.append(node_key)
            if node_keys:
                exact_keys.extend(node_keys)

            if exact_keys:
                memory_ids.extend(
                    self._find_memory_ids_by_node_keys(
                        node_keys=exact_keys,
                        top_k=top_k,
                        memory_type=memory_type,
                        session_id=session_id,
                        object_ids=object_ids,
                        node_type=node_type,
                    )
                )

            if node_query:
                memory_ids.extend(
                    self._find_memory_ids_by_node_query(
                        node_query=node_query,
                        top_k=top_k,
                        memory_type=memory_type,
                        session_id=session_id,
                        object_ids=object_ids,
                        node_type=node_type,
                    )
                )

            seen: set[str] = set()
            unique_memory_ids: list[str] = []

            for mid in memory_ids:
                if not mid or mid in seen:
                    continue
                seen.add(mid)
                unique_memory_ids.append(mid)

            out["memory_items"] = self._get_memory_items_by_ids(unique_memory_ids[:top_k])

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

            memory_ids = [str(it["id"]) for it in memory_items if "id" in it]

            if memory_ids:
                quoted_ids = ",".join(f"'{x}'" for x in memory_ids)

                # Delete old memory rows
                self._memory_table.delete(f"id IN ({quoted_ids})")

                # Delete old graph node occurrence rows linked to these memory ids
                self._memory_table.delete(
                    f"memory_id IN ({quoted_ids}) AND doc_kind = 'graph_node'"
                )

                result["deleted_ids"] = memory_ids

            # 1. Save memory item rows
            memory_texts = [it["page_content"] for it in memory_items]
            memory_vectors = self._embeddings.embed_documents(memory_texts)

            rows = [
                self._to_memory_row(item, vector)
                for item, vector in zip(memory_items, memory_vectors, strict=True)
            ]

            # 2. Save graph node occurrence rows
            graph_texts: list[str] = []
            graph_items: list[dict] = []

            for item in memory_items:
                metadata = item.get("metadata", {}) or {}
                graph_nodes = metadata.get("graph_nodes") or []

                valid_nodes = []
                for node in graph_nodes:
                    extra_data = node.get("extra_data") or {}
                    if extra_data.get("node_kind") == "memory_item":
                        continue

                    content = str(node.get("content", "")).strip()
                    if not content:
                        continue

                    valid_nodes.append(node)
                    graph_texts.append(content)

                if valid_nodes:
                    graph_items.append(
                        {
                            "item": item,
                            "valid_nodes": valid_nodes,
                        }
                    )

            graph_vectors = self._embeddings.embed_documents(graph_texts) if graph_texts else []

            vector_offset = 0
            for bundle in graph_items:
                item = bundle["item"]
                valid_nodes = bundle["valid_nodes"]
                node_vectors = graph_vectors[vector_offset : vector_offset + len(valid_nodes)]
                vector_offset += len(valid_nodes)

                # Temporarily pass only valid nodes into row builder
                item_copy = dict(item)
                metadata_copy = dict(item.get("metadata", {}) or {})
                metadata_copy["graph_nodes"] = valid_nodes
                item_copy["metadata"] = metadata_copy

                rows.extend(self._to_graph_node_rows(item_copy, node_vectors))

            if rows:
                self._memory_table.add(rows)

            result["inserted"] = len(rows)

        except Exception as e:
            result["error"] = str(e)

        return result

    #
    # Runner Interface
    #

    def _get_vdb_config(self, config: dict[str, Any]) -> dict[str, Any]:
        vdb_config = dict(config)
        vdb_config.pop("embedding", None)
        return vdb_config

    def _get_memory_embeddings(self, config: dict[str, Any]):
        embedding_config = config.get("embedding")

        if not embedding_config:
            raise ValueError("`embedding` is required in MEMORY_VDB_CONFIG")

        provider = embedding_config.get("provider")
        model = embedding_config.get("model")
        extra = embedding_config.get("extra") or {}

        if not provider:
            raise ValueError("`embedding.provider` is required in MEMORY_VDB_CONFIG")
        if not model:
            raise ValueError("`embedding.model` is required in MEMORY_VDB_CONFIG")

        task_config = ProviderTaskConfig(
            kind=ProviderKind.EMBEDDING,
            provider=provider,
            model=model,
            extra=extra,
        )

        return create_embedding_model(task_config)

    def initialize(self) -> None:
        config = os.getenv("MEMORY_VDB_CONFIG", "{}")
        config = json.loads(config)
        self._collection_name = config.get("collection_name", None)

        if not self._collection_name:
            raise ValueError("collection_name is required in MEMORY_VDB_CONFIG")

        self._client = lancedb.get_client(**self._get_vdb_config(config))

        self._embeddings = self._get_memory_embeddings(config)
        embedding_dim = len(self._embeddings.embed_query("dimension-probe"))

        self._ensure_collection(self._collection_name, embedding_dim)
        self._memory_table = self._client.open_table(self._collection_name)

    def run(self, data: bytes) -> bytes | None:
        json_data = json.loads(data)

        match json_data["op"]:
            case VectorRunnerOP.search_by_context:
                result = self._search_by_context(**json_data["param"])
                return json.dumps(result).encode()
            case VectorRunnerOP.search_by_graph_node:
                result = self._search_by_graph_node(**json_data["param"])
                return json.dumps(result).encode()
            case VectorRunnerOP.save:
                result = self._save(**json_data["param"])
                return json.dumps(result).encode()
            case _:
                return None
