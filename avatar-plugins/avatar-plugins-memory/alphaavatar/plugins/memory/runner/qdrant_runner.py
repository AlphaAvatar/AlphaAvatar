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

from langchain_qdrant import QdrantVectorStore
from livekit.agents.inference_runner import _InferenceRunner
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointIdsList,
    VectorParams,
)

from alphaavatar.agents.memory import VectorRunnerOP
from alphaavatar.agents.utils import get_embedding_model, get_qdrant_client


class QdrantRunner(_InferenceRunner):
    INFERENCE_METHOD = "alphaavatar_memory_qdrant"

    def __init__(self):
        super().__init__()

    def _ensure_collection(self, collection_name, embedding_dim) -> None:
        """Create collection if missing; infer embedding dimension dynamically (sync)."""
        try:
            self._client.get_collection(collection_name)
            return  # exists
        except Exception:
            pass

        self._client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=embedding_dim, distance=Distance.COSINE),
        )
        self._client.create_payload_index(
            collection_name=collection_name,
            field_name="metadata.object_id",
            field_schema=PayloadSchemaType.KEYWORD,
        )

    def _search_with_object_id(self, query_vec: list[float], obj_id: str, k: int):
        _filter = Filter(
            must=[FieldCondition(key="metadata.object_id", match=MatchValue(value=obj_id))]
        )
        points = self._client.search(
            collection_name=self._memory_collection_name,
            query_vector=query_vec,
            limit=k,
            query_filter=_filter,
            with_payload=True,
        )
        memory_items = []
        for p in points:
            payload = p.payload or {}
            doc = payload.get("page_content")
            meta = payload.get("metadata")
            memory_items.append({"id": str(p.id), "page_content": doc, "metadata": meta})
        return memory_items

    def _search_by_context(
        self,
        *,
        context_str: str,
        avatar_id: str,
        user_id: str | None = None,
        top_k: int = 10,
    ) -> dict:
        out = {
            "avatar_memory_items": [],
            "user_rmemory_items": [],
            "error": None,
        }

        try:
            query_vec = self._embeddings.embed_query(context_str)
            out["avatar_memory_items"] = self._search_with_object_id(query_vec, avatar_id, top_k)
            if user_id:
                out["user_rmemory_items"] = self._search_with_object_id(query_vec, user_id, top_k)
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

            ids = [it["id"] for it in memory_items if "id" in it]
            if ids:
                self._client.delete(
                    collection_name=self._memory_collection_name,
                    points_selector=PointIdsList(points=ids),
                    wait=True,
                )
                result["deleted_ids"] = ids

            texts = [it["page_content"] for it in memory_items]
            metadatas = [it["metadata"] for it in memory_items]
            self._memory_vector_store.add_texts(texts=texts, metadatas=metadatas, ids=ids)
            result["inserted"] = len(memory_items)

        except Exception as e:
            result["error"] = str(e)

        return result

    def initialize(self) -> None:
        # get config
        config = os.getenv("MEMORY_VDB_CONFIG", "{}")
        config = json.loads(config)
        self._memory_collection_name = config.get("memory_collection_name", None)

        # init client
        self._client = get_qdrant_client(**config)

        # init memory
        self._embeddings = get_embedding_model(**config)
        self._ensure_collection(
            self._memory_collection_name,
            len(self._embeddings.embed_query("dimension-probe")),
        )
        self._memory_vector_store = QdrantVectorStore(
            client=self._client,
            collection_name=self._memory_collection_name,
            embedding=self._embeddings,
        )

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
