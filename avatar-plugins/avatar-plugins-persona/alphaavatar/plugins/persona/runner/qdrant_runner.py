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
import shutil
from typing import Any

from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from livekit.agents.inference_runner import _InferenceRunner
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    VectorParams,
)

from ..enum.runner_op import EmbeddingRunnerOP


def get_qdrant_client(
    *,
    host: str | None = None,
    port: int | None = None,
    path: str = "/tmp/qdrant_profiler",
    url: str | None = None,
    api_key: str | None = None,
    on_disk: bool = False,
    prefer_grpc: bool = False,
    **kwargs,
):
    """
    Initialize Qdrant client.

    Args:
        host (str, optional): Qdrant server host (remote mode).
        port (int, optional): Qdrant server port (remote mode).
        path (str, optional): Local Qdrant DB path (local mode).
        url (str, optional): Full URL for Qdrant server (remote mode).
        api_key (str, optional): API key for Qdrant server (remote mode).
        on_disk (bool, optional): Keep local data directory if exists. Defaults to False.
        prefer_grpc (bool, optional): Prefer gRPC transport in remote mode.
    Returns:
        AsyncQdrantClient: The initialized asynchronous client.
    """
    is_remote = bool(url) or bool(api_key) or (host and port)

    if is_remote:
        # Remote synchronous client (HTTP 或 gRPC，取决于 prefer_grpc)
        client = QdrantClient(
            url=url if url else None,
            host=host if host else None,
            port=port if port else None,
            api_key=api_key if api_key else None,
            prefer_grpc=prefer_grpc,
        )
    else:
        # Local (embedded) synchronous client；本地模式不使用 gRPC
        if os.path.exists(path) and not on_disk and os.path.isdir(path):
            shutil.rmtree(path)
        client = QdrantClient(
            path=path,
            prefer_grpc=False,
        )

    return client


def get_profiler_embedding_model(*, profiler_embedding_model, **kwargs):
    embeddings = OpenAIEmbeddings(model=profiler_embedding_model)
    return embeddings


class QdrantRunner(_InferenceRunner):
    INFERENCE_METHOD = "alphaavatar_perona_qdrant"

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

    def _load_user_profile(self, *, user_id: str, **kwargs):
        def _scroll_all(filt: Filter | None):
            all_pts = []
            next_offset = None
            while True:
                try:
                    points, next_offset = self._client.scroll(
                        collection_name=self._profiler_collection_name,
                        limit=256,
                        with_payload=True,
                        with_vectors=False,
                        scroll_filter=filt,
                        offset=next_offset,
                    )
                except TypeError:
                    points, next_offset = self._client.scroll(
                        collection_name=self._profiler_collection_name,
                        limit=256,
                        with_payload=True,
                        with_vectors=False,
                        filter=filt,
                        offset=next_offset,
                    )
                all_pts.extend(points or [])
                if not next_offset or not points:
                    break
            return all_pts

        filt = Filter(
            must=[FieldCondition(key="metadata.user_id", match=MatchValue(value=user_id))]
        )
        all_points = _scroll_all(filt)

        if not all_points:
            all_points = _scroll_all(None)

            def _get_user_id(payload: dict[str, Any]) -> str | None:
                if not isinstance(payload, dict):
                    return None
                return (payload.get("metadata") or {}).get("user_id")

            all_points = [p for p in all_points if _get_user_id(p.payload or {}) == user_id]

        items: list[dict[str, Any]] = []
        for p in all_points:
            payload = p.payload or {}
            doc = payload.get("page_content")
            meta = payload.get("metadata")
            items.append({"id": str(p.id), "page_content": doc, "metadata": meta})

        return items

    def _save_user_profile(self, *, user_id: str, items: list[dict]) -> dict:
        result = {"user_id": user_id, "deleted": False, "inserted": 0, "error": None}
        try:
            filt = Filter(must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))])
            self._client.delete(
                collection_name=self._profiler_collection_name,
                points_selector=FilterSelector(filter=filt),
                wait=True,
            )
            result["deleted"] = True

            texts = [it["page_content"] for it in items]
            metadatas = [it["metadata"] for it in items]
            ids = [it["id"] for it in items]
            self._profiler_vector_store.add_texts(texts, metadatas, ids)
            result["inserted"] = len(items)

        except Exception as e:
            result["error"] = str(e)

        return result

    def initialize(self) -> None:
        # get config
        config = os.getenv("PERONA_EMBEDDING_CONFIG", "{}")
        config = json.loads(config)
        self._profiler_collection_name = config.get("profiler_collection_name", None)

        # init client
        self._client = get_qdrant_client(**config)

        # init profiler vs
        self._profiler_embeddings = get_profiler_embedding_model(**config)
        self._ensure_collection(
            self._profiler_collection_name,
            len(self._profiler_embeddings.embed_query("dimension-probe")),
        )
        self._profiler_vector_store = QdrantVectorStore(
            client=self._client,
            collection_name=self._profiler_collection_name,
            embedding=self._profiler_embeddings,
        )

        # init speaker vs

    def run(self, data: bytes) -> bytes | None:
        json_data = json.loads(data)

        match json_data["op"]:
            case EmbeddingRunnerOP.load_user_profile:
                items = self._load_user_profile(**json_data["param"])
                return json.dumps(items).encode()
            case EmbeddingRunnerOP.save_user_profile:
                result = self._save_user_profile(**json_data["param"])
                return json.dumps(result).encode()
            case _:
                return None
