# Copyright 2025 AlphaAvatar project
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
from uuid import NAMESPACE_URL, uuid5

from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchAny,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from alphaavatar.agents.memory.enums import VectorRunnerOP
from alphaavatar.agents.providers import ProviderKind, ProviderTaskConfig
from alphaavatar.agents.providers.embedding import create_embedding_model
from alphaavatar.agents.runtime.inference import InferenceRunner
from alphaavatar.agents.utils.vdb import qdrant


class QdrantRunner(InferenceRunner):
    INFERENCE_METHOD = "alphaavatar.memory.vdb.qdrant"

    _PAYLOAD_INDEX_FIELDS = (
        "doc_kind",
        "memory_id",
        "memory_kind",
        "memory_type",
        "scope_key",
        "owner_keys",
        "node_key",
        "node_type",
    )

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
    def _json_safe(value: Any, fallback: Any) -> Any:
        if value is None:
            return fallback
        try:
            return json.loads(json.dumps(value, ensure_ascii=False, default=str))
        except Exception:
            return fallback

    @staticmethod
    def _point_id(logical_id: str) -> str:
        return str(uuid5(NAMESPACE_URL, f"alphaavatar.memory.qdrant:{logical_id}"))

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

    def _build_filter(
        self,
        *,
        doc_kind: str | None = None,
        owner_keys: list[str] | None = None,
        scope_keys: list[str] | None = None,
        memory_type: str | None = None,
        memory_kind: str | None = None,
        node_type: str | None = None,
        node_keys: list[str] | None = None,
        memory_ids: list[str] | None = None,
    ) -> Filter | None:
        must = [
            FieldCondition(key=key, match=MatchValue(value=value))
            for key, value in (
                ("doc_kind", doc_kind),
                ("memory_type", memory_type),
                ("memory_kind", memory_kind),
                ("node_type", node_type),
            )
            if value
        ]

        for key, values in (
            ("owner_keys", owner_keys),
            ("scope_key", scope_keys),
            ("node_key", node_keys),
            ("memory_id", memory_ids),
        ):
            if values := self._as_str_list(values):
                must.append(FieldCondition(key=key, match=MatchAny(any=values)))

        return Filter(must=must) if must else None

    def _base_payload(self, item: dict) -> dict[str, Any]:
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
            "owner_refs": self._json_safe(metadata.get("owner_refs"), []),
            "participant_refs": self._json_safe(metadata.get("participant_refs"), []),
            "source_refs": self._json_safe(metadata.get("source_refs"), []),
            "topic": str(metadata.get("topic") or ""),
            "created_at": str(metadata.get("created_at", "")),
            "updated_at": str(metadata.get("updated_at", "")),
            "revision": int(metadata.get("revision") or 1),
            "source_memory_ids": self._as_str_list(metadata.get("source_memory_ids")),
            "supersedes_memory_ids": self._as_str_list(metadata.get("supersedes_memory_ids")),
        }

    def _to_memory_payload(self, item: dict) -> dict[str, Any]:
        metadata = item.get("metadata", {}) or {}
        return {
            "id": str(item["id"]),
            "page_content": item.get("page_content", ""),
            "doc_kind": "memory_item",
            **self._base_payload(item),
            "node_id": "",
            "node_key": "",
            "node_type": "",
            "node_weight": 0.0,
            "graph_nodes": self._json_safe(metadata.get("graph_nodes"), []),
            "graph_links": self._json_safe(metadata.get("graph_links"), []),
            "extra_data": self._json_safe(metadata.get("extra_data"), {}),
        }

    def _to_graph_node_payloads(
        self,
        item: dict,
        vectors: list[list[float]],
    ) -> list[tuple[dict[str, Any], list[float]]]:
        metadata = item.get("metadata", {}) or {}
        memory_id = str(item["id"])
        rows: list[tuple[dict[str, Any], list[float]]] = []

        for node, vector in zip(metadata.get("graph_nodes") or [], vectors, strict=True):
            extra_data = node.get("extra_data") or {}
            content = str(node.get("content", "")).strip()
            if extra_data.get("node_kind") == "memory_item" or not content:
                continue

            node_key = str(node.get("key") or node.get("id") or "")
            payload = {
                "id": f"graph_node::{memory_id}::{node_key}",
                "page_content": content,
                "doc_kind": "graph_node",
                **self._base_payload(item),
                "node_id": str(node.get("id", "")),
                "node_key": node_key,
                "node_type": str(node.get("type", "text")),
                "node_weight": float(node.get("weight", 1.0)),
                "graph_nodes": [],
                "graph_links": [],
                "extra_data": self._json_safe(extra_data, {}),
            }
            rows.append((payload, vector))

        return rows

    def _query_candidates(
        self,
        vector: list[float],
        *,
        query_filter: Filter | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []

        response = self._client.query_points(
            collection_name=self._collection_name,
            query=vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return [
            {"memory_id": memory_id, "score": float(point.score or 0.0)}
            for point in response.points
            if (memory_id := str((point.payload or {}).get("memory_id") or "").strip())
        ]

    def _scroll_candidates(
        self,
        *,
        scroll_filter: Filter | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []

        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        offset = None

        while len(out) < limit:
            records, next_offset = self._client.scroll(
                collection_name=self._collection_name,
                scroll_filter=scroll_filter,
                limit=min(max(limit * 2, 64), 256),
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )

            for record in records:
                memory_id = str((record.payload or {}).get("memory_id") or "").strip()
                if memory_id and memory_id not in seen:
                    seen.add(memory_id)
                    out.append({"memory_id": memory_id, "score": 1.0})
                    if len(out) >= limit:
                        break

            if next_offset is None or not records:
                break
            offset = next_offset

        return out

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
                query_filter=self._build_filter(doc_kind="memory_item", **common),
                limit=top_k,
            )
            graph = self._query_candidates(
                vector,
                query_filter=self._build_filter(doc_kind="graph_node", **common),
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
                self._scroll_candidates(
                    scroll_filter=self._build_filter(node_keys=node_keys, **common),
                    limit=top_k,
                )
                if self._as_str_list(node_keys)
                else []
            )
            semantic = (
                self._query_candidates(
                    self._embeddings.embed_query(node_query),
                    query_filter=self._build_filter(**common),
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

            query_filter = self._build_filter(
                doc_kind="memory_item",
                owner_keys=owner_keys,
                scope_keys=scope_keys,
                memory_type=memory_type,
                memory_kind=layer,
            )
            out["results"] = [
                self._query_candidates(vector, query_filter=query_filter, limit=top_k)
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
                self._client.delete(
                    collection_name=self._collection_name,
                    points_selector=FilterSelector(
                        filter=self._build_filter(memory_ids=memory_ids)
                    ),
                    wait=True,
                )
                result["deleted_ids"] = memory_ids

            memory_texts = [
                item.get("embedding_text") or item.get("page_content", "") for item in memory_items
            ]
            memory_vectors = self._embeddings.embed_documents(memory_texts)
            points = [
                PointStruct(
                    id=self._point_id(f"memory_item::{item['id']}"),
                    vector=vector,
                    payload=self._to_memory_payload(item),
                )
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

                for payload, node_vector in self._to_graph_node_payloads(item_copy, [vector]):
                    points.append(
                        PointStruct(
                            id=self._point_id(payload["id"]),
                            vector=node_vector,
                            payload=payload,
                        )
                    )

            if points:
                self._client.upsert(
                    collection_name=self._collection_name,
                    points=points,
                    wait=True,
                )

            result["inserted"] = len(points)
        except Exception as exc:
            result["error"] = str(exc)

        return result

    def _ensure_collection(self, collection_name: str, embedding_dim: int) -> None:
        if not self._client.collection_exists(collection_name):
            self._client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=embedding_dim, distance=Distance.COSINE),
            )

        indexed_fields = set(
            (self._client.get_collection(collection_name).payload_schema or {}).keys()
        )

        for field in self._PAYLOAD_INDEX_FIELDS:
            if field not in indexed_fields:
                self._client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field,
                    field_schema=PayloadSchemaType.KEYWORD,
                    wait=True,
                )

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

        self._client = qdrant.get_client(**self._get_vdb_config(config))
        self._embeddings = self._get_memory_embeddings(config)
        embedding_dim = len(self._embeddings.embed_query("dimension-probe"))
        self._ensure_collection(self._collection_name, embedding_dim)

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
