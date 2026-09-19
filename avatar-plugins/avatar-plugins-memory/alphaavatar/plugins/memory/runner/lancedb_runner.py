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

from alphaavatar.agents.memory.enums import VectorRunnerOP
from alphaavatar.agents.providers import ProviderKind, ProviderTaskConfig
from alphaavatar.agents.providers.embedding import create_embedding_model
from alphaavatar.agents.runtime.inference import InferenceRunner
from alphaavatar.agents.utils.vdb import lancedb


class LanceDBRunner(InferenceRunner):
    INFERENCE_METHOD = "alphaavatar.memory.vdb.lancedb"

    _REQUIRED_COLUMNS = {
        "id",
        "vector",
        "page_content",
        "doc_kind",
        "memory_id",
        "memory_kind",
        "memory_type",
        "episode_idcontext_id",
        "runtime_session_id",
        "parent_context_id",
        "task_id",
        "scope_key",
        "owner_keys",
        "owner_refs_json",
        "participant_refs_json",
        "source_refs_json",
        "topic",
        "created_at",
        "updated_at",
        "revision",
        "source_memory_ids_json",
        "supersedes_memory_ids_json",
        "node_id",
        "node_key",
        "node_type",
        "node_weight",
        "graph_nodes_json",
        "graph_links_json",
        "extra_data_json",
    }

    def __init__(self):
        super().__init__()

    @staticmethod
    def _as_str_list(value: Any) -> list[str]:
        if value is None:
            return []
        values = value if isinstance(value, list | tuple | set) else [value]
        out: list[str] = []
        seen: set[str] = set()
        for item in values:
            if item is None:
                continue
            item = str(item).strip()
            if item and item not in seen:
                seen.add(item)
                out.append(item)
        return out

    @staticmethod
    def _json_dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)

    @staticmethod
    def _quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    @classmethod
    def _sql_list(cls, values: list[str]) -> str:
        return "[" + ",".join(cls._quote(value) for value in values) + "]"

    @classmethod
    def _sql_in(cls, values: list[str]) -> str:
        return "(" + ",".join(cls._quote(value) for value in values) + ")"

    @classmethod
    def _where(
        cls,
        *,
        doc_kind: str | None = None,
        owner_keys: list[str] | None = None,
        scope_keys: list[str] | None = None,
        memory_type: str | None = None,
        memory_kind: str | None = None,
        node_type: str | None = None,
        node_keys: list[str] | None = None,
    ) -> str:
        parts = [
            f"{key} = {cls._quote(value)}"
            for key, value in (
                ("doc_kind", doc_kind),
                ("memory_type", memory_type),
                ("memory_kind", memory_kind),
                ("node_type", node_type),
            )
            if value
        ]
        if owners := cls._as_str_list(owner_keys):
            parts.append(f"array_contains_any(owner_keys, {cls._sql_list(owners)})")
        if scopes := cls._as_str_list(scope_keys):
            parts.append(f"scope_key IN {cls._sql_in(scopes)}")
        if keys := cls._as_str_list(node_keys):
            parts.append(f"node_key IN {cls._sql_in(keys)}")
        return " AND ".join(parts) if parts else "true"

    @staticmethod
    def _merge_candidates(*groups: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        merged: dict[str, float] = {}
        for group in groups:
            for candidate in group:
                memory_id = str(candidate.get("memory_id") or "").strip()
                if not memory_id:
                    continue
                score = float(candidate.get("score") or 0.0)
                merged[memory_id] = max(score, merged.get(memory_id, float("-inf")))
        return [
            {"memory_id": memory_id, "score": score}
            for memory_id, score in sorted(merged.items(), key=lambda item: item[1], reverse=True)[
                :limit
            ]
        ]

    def _ensure_collection(self, collection_name: str, embedding_dim: int) -> None:
        if self._client.table_exists(collection_name):
            return

        seed = [
            {
                "id": "__init__",
                "vector": [0.0] * embedding_dim,
                "page_content": "__init__",
                "doc_kind": "memory_item",
                "memory_id": "",
                "memory_kind": "",
                "memory_type": "",
                "episode_id": "",
                "context_id": "",
                "runtime_session_id": "",
                "parent_context_id": "",
                "task_id": "",
                "scope_key": "",
                "owner_keys": ["__init__"],
                "owner_refs_json": "[]",
                "participant_refs_json": "[]",
                "source_refs_json": "[]",
                "topic": "",
                "created_at": "",
                "updated_at": "",
                "revision": 1,
                "source_memory_ids_json": "[]",
                "supersedes_memory_ids_json": "[]",
                "node_id": "",
                "node_key": "",
                "node_type": "",
                "node_weight": 0.0,
                "graph_nodes_json": "[]",
                "graph_links_json": "[]",
                "extra_data_json": "{}",
            }
        ]
        table = self._client.create_table(collection_name, seed)
        table.delete("id = '__init__'")

    def _validate_collection_schema(self) -> None:
        missing = sorted(self._REQUIRED_COLUMNS - set(self._memory_table.schema.names))
        if missing:
            raise RuntimeError(
                "Memory LanceDB schema is incompatible with the current index model; "
                f"missing columns: {', '.join(missing)}. Recreate the memory collection."
            )

    def _base_row(self, item: dict) -> dict[str, Any]:
        metadata = item.get("metadata", {}) or {}
        return {
            "memory_id": str(item["id"]),
            "memory_kind": str(metadata.get("memory_kind", "")),
            "memory_type": str(metadata.get("memory_type", "")),
            "episode_id": str(metadata.get("episode_id", "")),
            "context_id": str(metadata.get("context_id", "")),
            "runtime_session_id": str(metadata.get("runtime_session_id") or ""),
            "parent_context_id": str(metadata.get("parent_context_id") or ""),
            "task_id": str(metadata.get("task_id") or ""),
            "scope_key": str(metadata.get("scope_key", "")),
            "owner_keys": self._as_str_list(metadata.get("owner_keys")),
            "owner_refs_json": self._json_dumps(metadata.get("owner_refs") or []),
            "participant_refs_json": self._json_dumps(metadata.get("participant_refs") or []),
            "source_refs_json": self._json_dumps(metadata.get("source_refs") or []),
            "topic": str(metadata.get("topic") or ""),
            "created_at": str(metadata.get("created_at", "")),
            "updated_at": str(metadata.get("updated_at", "")),
            "revision": int(metadata.get("revision") or 1),
            "source_memory_ids_json": self._json_dumps(metadata.get("source_memory_ids") or []),
            "supersedes_memory_ids_json": self._json_dumps(
                metadata.get("supersedes_memory_ids") or []
            ),
        }

    def _to_memory_row(self, item: dict, vector: list[float]) -> dict[str, Any]:
        metadata = item.get("metadata", {}) or {}
        return {
            "id": str(item["id"]),
            "vector": vector,
            "page_content": item.get("page_content", ""),
            "doc_kind": "memory_item",
            **self._base_row(item),
            "node_id": "",
            "node_key": "",
            "node_type": "",
            "node_weight": 0.0,
            "graph_nodes_json": self._json_dumps(metadata.get("graph_nodes") or []),
            "graph_links_json": self._json_dumps(metadata.get("graph_links") or []),
            "extra_data_json": self._json_dumps(metadata.get("extra_data") or {}),
        }

    def _to_graph_node_rows(self, item: dict, vectors: list[list[float]]) -> list[dict[str, Any]]:
        metadata = item.get("metadata", {}) or {}
        memory_id = str(item["id"])
        rows: list[dict[str, Any]] = []

        for node, vector in zip(metadata.get("graph_nodes") or [], vectors, strict=True):
            extra_data = node.get("extra_data") or {}
            content = str(node.get("content", "")).strip()
            if extra_data.get("node_kind") == "memory_item" or not content:
                continue

            node_key = str(node.get("key") or node.get("id") or "")
            rows.append(
                {
                    "id": f"graph_node::{memory_id}::{node_key}",
                    "vector": vector,
                    "page_content": content,
                    "doc_kind": "graph_node",
                    **self._base_row(item),
                    "node_id": str(node.get("id", "")),
                    "node_key": node_key,
                    "node_type": str(node.get("type", "text")),
                    "node_weight": float(node.get("weight", 1.0)),
                    "graph_nodes_json": "[]",
                    "graph_links_json": "[]",
                    "extra_data_json": self._json_dumps(extra_data),
                }
            )

        return rows

    def _query_candidates(
        self,
        vector: list[float],
        *,
        where: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []

        rows = (
            self._memory_table.search(vector)
            .metric("cosine")
            .where(where)
            .select(["memory_id"])
            .limit(limit)
            .to_list()
        )
        return [
            {"memory_id": memory_id, "score": 1.0 - float(row.get("_distance", 1.0))}
            for row in rows
            if (memory_id := str(row.get("memory_id") or "").strip())
        ]

    def _filter_candidates(self, *, where: str, limit: int) -> list[dict[str, Any]]:
        if limit <= 0:
            return []

        rows = self._memory_table.search().where(where).select(["memory_id"]).limit(limit).to_list()
        return self._merge_candidates(
            [
                {"memory_id": memory_id, "score": 1.0}
                for row in rows
                if (memory_id := str(row.get("memory_id") or "").strip())
            ],
            limit=limit,
        )

    def _search_by_context(
        self,
        *,
        context_str: str,
        owner_keys: list[str] | None = None,
        scope_keys: list[str] | None = None,
        top_k: int = 10,
    ) -> dict[str, Any]:
        out = {"candidates": [], "error": None}
        try:
            vector = self._embeddings.embed_query(context_str)
            common = {"owner_keys": owner_keys, "scope_keys": scope_keys}
            memories = self._query_candidates(
                vector,
                where=self._where(doc_kind="memory_item", **common),
                limit=top_k,
            )
            graph = self._query_candidates(
                vector,
                where=self._where(doc_kind="graph_node", **common),
                limit=top_k,
            )
            out["candidates"] = self._merge_candidates(memories, graph, limit=top_k)
        except Exception as exc:
            out["error"] = str(exc)
        return out

    def _search_by_graph_node(
        self,
        *,
        node_keys: list[str] | None = None,
        node_query: str | None = None,
        owner_keys: list[str] | None = None,
        scope_keys: list[str] | None = None,
        memory_type: str | None = None,
        node_type: str | None = None,
        top_k: int = 50,
    ) -> dict[str, Any]:
        out = {"candidates": [], "error": None}
        try:
            common = {
                "doc_kind": "graph_node",
                "owner_keys": owner_keys,
                "scope_keys": scope_keys,
                "memory_type": memory_type,
                "node_type": node_type,
            }
            exact = (
                self._filter_candidates(
                    where=self._where(node_keys=node_keys, **common), limit=top_k
                )
                if self._as_str_list(node_keys)
                else []
            )
            semantic = (
                self._query_candidates(
                    self._embeddings.embed_query(node_query),
                    where=self._where(**common),
                    limit=top_k,
                )
                if node_query and node_query.strip()
                else []
            )
            out["candidates"] = self._merge_candidates(exact, semantic, limit=top_k)
        except Exception as exc:
            out["error"] = str(exc)
        return out

    def _search_similar_batch(
        self,
        *,
        texts: list[str],
        top_k: int = 5,
        owner_keys: list[str] | None = None,
        scope_keys: list[str] | None = None,
        memory_type: str | None = None,
        layer: str | None = None,
    ) -> dict[str, Any]:
        out = {"results": [], "error": None}
        try:
            if not texts:
                return out
            if top_k <= 0:
                out["results"] = [[] for _ in texts]
                return out

            where = self._where(
                doc_kind="memory_item",
                owner_keys=owner_keys,
                scope_keys=scope_keys,
                memory_type=memory_type,
                memory_kind=layer,
            )
            out["results"] = [
                self._query_candidates(vector, where=where, limit=top_k)
                for vector in self._embeddings.embed_documents(texts)
            ]
        except Exception as exc:
            out["error"] = str(exc)
            out["results"] = [[] for _ in texts]
        return out

    def _save(self, *, memory_items: list[dict]) -> dict[str, Any]:
        result = {"deleted_ids": [], "inserted": 0, "error": None}
        try:
            if not memory_items:
                return result

            memory_ids = self._as_str_list(
                item.get("id") for item in memory_items if item.get("id")
            )
            if memory_ids:
                self._memory_table.delete(f"memory_id IN {self._sql_in(memory_ids)}")
                result["deleted_ids"] = memory_ids

            memory_texts = [
                item.get("embedding_text") or item.get("page_content", "") for item in memory_items
            ]
            memory_vectors = self._embeddings.embed_documents(memory_texts)
            rows = [
                self._to_memory_row(item, vector)
                for item, vector in zip(memory_items, memory_vectors, strict=True)
            ]

            graph_nodes: list[tuple[dict, dict]] = []
            graph_texts: list[str] = []
            for item in memory_items:
                for node in item.get("metadata", {}).get("graph_nodes") or []:
                    extra_data = node.get("extra_data") or {}
                    content = str(node.get("content", "")).strip()
                    if extra_data.get("node_kind") == "memory_item" or not content:
                        continue
                    graph_nodes.append((item, node))
                    graph_texts.append(content)

            graph_vectors = self._embeddings.embed_documents(graph_texts) if graph_texts else []
            for (item, node), vector in zip(graph_nodes, graph_vectors, strict=True):
                item_copy = dict(item)
                metadata = dict(item_copy.get("metadata", {}) or {})
                metadata["graph_nodes"] = [node]
                item_copy["metadata"] = metadata
                rows.extend(self._to_graph_node_rows(item_copy, [vector]))

            if rows:
                self._memory_table.add(rows)
            result["inserted"] = len(rows)
        except Exception as exc:
            result["error"] = str(exc)
        return result

    @staticmethod
    def _get_vdb_config(config: dict[str, Any]) -> dict[str, Any]:
        vdb_config = dict(config)
        vdb_config.pop("embedding", None)
        return vdb_config

    @staticmethod
    def _get_memory_embeddings(config: dict[str, Any]):
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

        return create_embedding_model(
            ProviderTaskConfig(
                kind=ProviderKind.EMBEDDING,
                provider=provider,
                model=model,
                extra=extra,
            )
        )

    def initialize(self) -> None:
        config = json.loads(os.getenv("MEMORY_VDB_CONFIG", "{}"))
        self._collection_name = config.get("collection_name")
        if not self._collection_name:
            raise ValueError("collection_name is required in MEMORY_VDB_CONFIG")

        self._client = lancedb.get_client(**self._get_vdb_config(config))
        self._embeddings = self._get_memory_embeddings(config)
        embedding_dim = len(self._embeddings.embed_query("dimension-probe"))
        self._ensure_collection(self._collection_name, embedding_dim)
        self._memory_table = self._client.open_table(self._collection_name)
        self._validate_collection_schema()

    def run(self, data: bytes) -> bytes | None:
        json_data = json.loads(data)

        match json_data["op"]:
            case VectorRunnerOP.search_by_context:
                result = self._search_by_context(**json_data["param"])
            case VectorRunnerOP.search_by_graph_node:
                result = self._search_by_graph_node(**json_data["param"])
            case VectorRunnerOP.search_similar_batch:
                result = self._search_similar_batch(**json_data["param"])
            case VectorRunnerOP.save:
                result = self._save(**json_data["param"])
            case _:
                return None

        return json.dumps(result).encode()
