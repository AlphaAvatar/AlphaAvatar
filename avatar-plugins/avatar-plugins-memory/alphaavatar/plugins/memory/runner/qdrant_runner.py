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

from alphaavatar.agents.memory import VectorRunnerOP
from alphaavatar.agents.providers import ProviderKind, ProviderTaskConfig
from alphaavatar.agents.providers.embedding import create_embedding_model
from alphaavatar.agents.runtime.inference import InferenceRunner
from alphaavatar.agents.utils.vdb import qdrant


class QdrantRunner(InferenceRunner):
    INFERENCE_METHOD = "alphaavatar.memory.vdb.qdrant"

    _PAYLOAD_INDEX_FIELDS = (
        "doc_kind",
        "memory_id",
        "node_key",
        "node_type",
        "memory_type",
        "session_id",
        "object_ids",
    )

    def __init__(self):
        super().__init__()

    """Helper Op"""

    @staticmethod
    def _as_str_list(value: Any) -> list[str]:
        if value is None:
            return []

        values = value if isinstance(value, list | tuple) else [value]
        out: list[str] = []
        seen: set[str] = set()

        for item in values:
            value = str(item).strip()
            if not value or value in seen:
                continue
            seen.add(value)
            out.append(value)

        return out

    @staticmethod
    def _json_safe(value: Any, fallback: Any) -> Any:
        if value is None:
            return fallback

        try:
            return json.loads(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    default=str,
                )
            )
        except Exception:
            return fallback

    @staticmethod
    def _point_id(logical_id: str) -> str:
        """Qdrant physical ID. AlphaAvatar logical ID remains in payload."""
        return str(
            uuid5(
                NAMESPACE_URL,
                f"alphaavatar.memory.qdrant:{logical_id}",
            )
        )

    def _build_filter(
        self,
        *,
        doc_kind: str | None = None,
        object_ids: list[str] | None = None,
        memory_type: str | None = None,
        session_id: str | None = None,
        node_type: str | None = None,
        node_keys: list[str] | None = None,
        memory_ids: list[str] | None = None,
    ) -> Filter | None:
        must = []

        for key, value in (
            ("doc_kind", doc_kind),
            ("memory_type", memory_type),
            ("session_id", session_id),
            ("node_type", node_type),
        ):
            if value:
                must.append(
                    FieldCondition(
                        key=key,
                        match=MatchValue(value=value),
                    )
                )

        if values := self._as_str_list(object_ids):
            must.append(
                FieldCondition(
                    key="object_ids",
                    match=MatchAny(any=values),
                )
            )

        if values := self._as_str_list(node_keys):
            must.append(
                FieldCondition(
                    key="node_key",
                    match=MatchAny(any=values),
                )
            )

        if values := self._as_str_list(memory_ids):
            must.append(
                FieldCondition(
                    key="memory_id",
                    match=MatchAny(any=values),
                )
            )

        return Filter(must=must) if must else None

    """Qdrant row conversion"""

    def _to_memory_payload(self, item: dict) -> dict[str, Any]:
        metadata = item.get("metadata", {}) or {}
        memory_id = str(item["id"])

        return {
            "id": memory_id,
            "page_content": item.get("page_content", ""),
            "doc_kind": "memory_item",
            "session_id": str(metadata.get("session_id", "")),
            "object_ids": self._as_str_list(metadata.get("object_ids")),
            "topic": str(metadata.get("topic", "")),
            "created_at": str(metadata.get("created_at", "")),
            "memory_type": str(metadata.get("memory_type", "")),
            "memory_id": memory_id,
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

        vector_idx = 0

        for node in metadata.get("graph_nodes") or []:
            extra_data = node.get("extra_data") or {}

            # memory_item already has its own row.
            if extra_data.get("node_kind") == "memory_item":
                continue

            content = str(node.get("content", "")).strip()
            if not content:
                continue

            node_key = str(node.get("key", "") or node.get("id", ""))
            node_id = str(node.get("id", ""))
            row_id = f"graph_node::{memory_id}::{node_key}"

            payload = {
                "id": row_id,
                "page_content": content,
                "doc_kind": "graph_node",
                "session_id": str(metadata.get("session_id", "")),
                "object_ids": self._as_str_list(metadata.get("object_ids")),
                "topic": str(metadata.get("topic", "")),
                "created_at": str(metadata.get("created_at", "")),
                "memory_type": str(metadata.get("memory_type", "")),
                "memory_id": memory_id,
                "node_id": node_id,
                "node_key": node_key,
                "node_type": str(node.get("type", "text")),
                "node_weight": float(node.get("weight", 1.0)),
                "graph_nodes": [],
                "graph_links": [],
                "extra_data": self._json_safe(extra_data, {}),
            }

            rows.append((payload, vectors[vector_idx]))
            vector_idx += 1

        return rows

    @staticmethod
    def _payload_to_item(payload: dict[str, Any]) -> dict:
        return {
            "id": str(payload.get("id", "")),
            "page_content": payload.get("page_content", ""),
            "metadata": {
                "session_id": payload.get("session_id", ""),
                "object_ids": payload.get("object_ids") or [],
                "topic": payload.get("topic", ""),
                "created_at": payload.get("created_at", ""),
                "memory_type": payload.get("memory_type", ""),
                "graph_nodes": payload.get("graph_nodes") or [],
                "graph_links": payload.get("graph_links") or [],
                "extra_data": payload.get("extra_data") or {},
            },
        }

    """Qdrant query helpers"""

    def _query_payloads(
        self,
        query_vec: list[float],
        *,
        query_filter: Filter | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []

        response = self._client.query_points(
            collection_name=self._collection_name,
            query=query_vec,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )

        return [dict(point.payload or {}) for point in response.points]

    def _scroll_payloads(
        self,
        *,
        scroll_filter: Filter | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []

        out: list[dict[str, Any]] = []
        offset = None

        while len(out) < limit:
            records, next_offset = self._client.scroll(
                collection_name=self._collection_name,
                scroll_filter=scroll_filter,
                limit=min(256, limit - len(out)),
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )

            out.extend(dict(record.payload or {}) for record in records)

            if next_offset is None or not records:
                break

            offset = next_offset

        return out

    def _get_memory_items_by_ids(
        self,
        memory_ids: list[str],
    ) -> list[dict]:
        ordered_ids = self._as_str_list(memory_ids)
        if not ordered_ids:
            return []

        rows = self._scroll_payloads(
            scroll_filter=self._build_filter(
                doc_kind="memory_item",
                memory_ids=ordered_ids,
            ),
            limit=len(ordered_ids),
        )

        item_by_id = {
            str(row.get("memory_id", "")): self._payload_to_item(row)
            for row in rows
            if row.get("memory_id")
        }

        return [item_by_id[memory_id] for memory_id in ordered_ids if memory_id in item_by_id]

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
        keys = self._as_str_list(node_keys)
        if not keys or top_k <= 0:
            return []

        query_filter = self._build_filter(
            doc_kind="graph_node",
            node_keys=keys,
            node_type=node_type,
            memory_type=memory_type,
            session_id=session_id,
            object_ids=object_ids,
        )

        out: list[str] = []
        seen: set[str] = set()
        offset = None

        while len(out) < top_k:
            records, next_offset = self._client.scroll(
                collection_name=self._collection_name,
                scroll_filter=query_filter,
                limit=max(64, top_k * 4),
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )

            for record in records:
                memory_id = str((record.payload or {}).get("memory_id", ""))

                if not memory_id or memory_id in seen:
                    continue

                seen.add(memory_id)
                out.append(memory_id)

                if len(out) >= top_k:
                    break

            if next_offset is None or not records:
                break

            offset = next_offset

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
        if not node_query.strip() or top_k <= 0:
            return []

        rows = self._query_payloads(
            self._embeddings.embed_query(node_query),
            query_filter=self._build_filter(
                doc_kind="graph_node",
                node_type=node_type,
                memory_type=memory_type,
                session_id=session_id,
                object_ids=object_ids,
            ),
            limit=max(top_k * 16, 64),
        )

        out: list[str] = []
        seen: set[str] = set()

        for row in rows:
            memory_id = str(row.get("memory_id", ""))

            if not memory_id or memory_id in seen:
                continue

            seen.add(memory_id)
            out.append(memory_id)

            if len(out) >= top_k:
                break

        return out

    """Search Op"""

    def _search_rows(
        self,
        query_vec: list[float],
        *,
        object_ids: list[str] | None,
        doc_kind: str,
        k: int,
    ) -> list[dict[str, Any]]:
        return self._query_payloads(
            query_vec,
            query_filter=self._build_filter(
                doc_kind=doc_kind,
                object_ids=object_ids,
            ),
            limit=k,
        )

    def _search_by_context(
        self,
        *,
        context_str: str,
        object_ids: list[str] | None = None,
        top_k: int = 10,
    ) -> dict:
        out = {"memory_items": [], "error": None}

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
                item = self._payload_to_item(row)
                merged[item["id"]] = item

            graph_memory_ids = [
                str(row.get("memory_id", "")) for row in graph_rows if row.get("memory_id")
            ]

            for item in self._get_memory_items_by_ids(graph_memory_ids):
                merged[item["id"]] = item

            out["memory_items"] = list(merged.values())[:top_k]

        except Exception as exc:
            out["error"] = str(exc)

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
        out = {"memory_items": [], "error": None}

        try:
            memory_ids: list[str] = []

            exact_keys = self._as_str_list([node_key, *(node_keys or [])])
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

            out["memory_items"] = self._get_memory_items_by_ids(
                self._as_str_list(memory_ids)[:top_k]
            )

        except Exception as exc:
            out["error"] = str(exc)

        return out

    """Save Op"""

    def _save(self, *, memory_items: list[dict]) -> dict:
        result = {
            "deleted_ids": [],
            "inserted": 0,
            "error": None,
        }

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

            # 1. Memory item embeddings.
            memory_vectors = self._embeddings.embed_documents(
                [item.get("page_content", "") for item in memory_items]
            )

            points: list[PointStruct] = []

            for item, vector in zip(
                memory_items,
                memory_vectors,
                strict=True,
            ):
                payload = self._to_memory_payload(item)

                points.append(
                    PointStruct(
                        id=self._point_id(f"memory_item::{payload['memory_id']}"),
                        vector=vector,
                        payload=payload,
                    )
                )

            # 2. Graph node embeddings.
            graph_texts: list[str] = []
            graph_items: list[dict] = []

            for item in memory_items:
                valid_nodes = []

                for node in item.get("metadata", {}).get("graph_nodes") or []:
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

                item_copy = dict(item)
                metadata = dict(item.get("metadata", {}) or {})
                metadata["graph_nodes"] = valid_nodes
                item_copy["metadata"] = metadata

                node_vectors = graph_vectors[vector_offset : vector_offset + len(valid_nodes)]
                vector_offset += len(valid_nodes)

                for payload, vector in self._to_graph_node_payloads(
                    item_copy,
                    node_vectors,
                ):
                    points.append(
                        PointStruct(
                            id=self._point_id(payload["id"]),
                            vector=vector,
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

    """Runner Interface"""

    def _ensure_collection(self, collection_name: str, embedding_dim: int) -> None:
        if not self._client.collection_exists(collection_name):
            self._client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=embedding_dim,
                    distance=Distance.COSINE,
                ),
            )

        collection = self._client.get_collection(collection_name)
        indexed_fields = set((collection.payload_schema or {}).keys())

        for field in self._PAYLOAD_INDEX_FIELDS:
            if field in indexed_fields:
                continue

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
            case VectorRunnerOP.save:
                result = self._save(**json_data["param"])
            case _:
                return None

        return json.dumps(result).encode()
