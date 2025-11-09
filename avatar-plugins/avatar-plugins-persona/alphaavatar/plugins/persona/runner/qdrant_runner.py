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
from uuid import uuid4

from langchain_qdrant import QdrantVectorStore
from livekit.agents.inference_runner import _InferenceRunner
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    SearchParams,
    VectorParams,
)

from alphaavatar.agents.persona import VectorRunnerOP
from alphaavatar.agents.utils import get_embedding_model, get_qdrant_client

from ..models import MODEL_CONFIG
from .speaker_vector_runner import SpeakerVectorRunner


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
        self._client.create_payload_index(
            collection_name=collection_name,
            field_name="metadata.user_id",
            field_schema=PayloadSchemaType.KEYWORD,
        )
        self._client.create_payload_index(
            collection_name=collection_name,
            field_name="user_id",
            field_schema=PayloadSchemaType.KEYWORD,
        )

    def _scroll_all(self, filt: Filter | None, collection_name, *, with_vectors: bool = False):
        all_pts = []
        next_offset = None
        while True:
            try:
                points, next_offset = self._client.scroll(
                    collection_name=collection_name,
                    limit=256,
                    with_payload=True,
                    with_vectors=with_vectors,
                    scroll_filter=filt,
                    offset=next_offset,
                )
            except TypeError:
                points, next_offset = self._client.scroll(
                    collection_name=collection_name,
                    limit=256,
                    with_payload=True,
                    with_vectors=with_vectors,
                    filter=filt,
                    offset=next_offset,
                )
            all_pts.extend(points or [])
            if not next_offset or not points:
                break
        return all_pts

    def _save_batch_speaker_vector(self, *, items: list[dict]) -> dict:
        result = {"inserted": 0, "error": None}
        try:
            points: list[PointStruct] = []
            for it in items:
                vid = str(it.get("id") or uuid4())
                vec = it["vector"]
                payload = it.get("payload") or {}
                points.append(PointStruct(id=vid, vector=vec, payload=payload))

            self._client.upsert(
                collection_name=self._speaker_collection_name, points=points, wait=True
            )
            result["inserted"] = len(points)
        except Exception as e:
            result["error"] = str(e)
        return result

    def _load(self, *, user_id: str, **kwargs) -> dict:
        # 1) Load details_items from profiler collection
        details_items: list[dict[str, Any]] = []
        filt = Filter(
            must=[FieldCondition(key="metadata.user_id", match=MatchValue(value=user_id))]
        )
        all_points = self._scroll_all(filt, self._profiler_collection_name, with_vectors=False)
        for p in all_points:
            payload = p.payload or {}
            doc = payload.get("page_content")
            meta = payload.get("metadata")
            details_items.append({"id": str(p.id), "page_content": doc, "metadata": meta})

        # 2) Load speaker vector from speaker collection
        speaker_vector = None
        spk_filter = Filter(
            should=[
                FieldCondition(key="user_id", match=MatchValue(value=user_id)),
            ]
        )
        spk_points = self._scroll_all(spk_filter, self._speaker_collection_name, with_vectors=True)
        if spk_points:
            # take the most recent / first found
            p = spk_points[0]
            hv = getattr(p, "vector", None)
            if isinstance(hv, dict):
                if hv:
                    speaker_vector = next(iter(hv.values()))
            else:
                speaker_vector = hv

        return {"details_items": details_items, "speaker_vector": speaker_vector}

    def _save(
        self, *, user_id: str, details_items: list[dict] | None, speaker_vector: list[float] | None
    ) -> dict:
        result = {
            "user_id": user_id,
            "deleted": False,
            "inserted": 0,
            "error": None,
            "speaker_deleted": False,
            "speaker_inserted": 0,
            "speaker_error": None,
        }

        # 1) Save details_items to profiler collection
        if details_items:
            try:
                filt = Filter(
                    must=[FieldCondition(key="metadata.user_id", match=MatchValue(value=user_id))]
                )
                self._client.delete(
                    collection_name=self._profiler_collection_name,
                    points_selector=FilterSelector(filter=filt),
                    wait=True,
                )
                result["deleted"] = True

                texts = [it["page_content"] for it in details_items]
                metadatas = [it["metadata"] for it in details_items]
                ids = [it["id"] for it in details_items]
                self._profiler_vector_store.add_texts(texts, metadatas, ids)
                result["inserted"] = len(details_items)
            except Exception as e:
                result["error"] = str(e)

        # 2) Save speaker vector to speaker collection
        if speaker_vector:
            try:
                # delete existing speaker vectors for this user (support both payload schemas)
                speaker_filt = Filter(
                    must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
                )
                self._client.delete(
                    collection_name=self._speaker_collection_name,
                    points_selector=FilterSelector(filter=speaker_filt),
                    wait=True,
                )
                result["speaker_deleted"] = True

                # upsert the new vector
                payload = {"user_id": user_id}
                save_res = self._save_batch_speaker_vector(
                    items=[{"vector": speaker_vector, "payload": payload}]
                )
                if save_res.get("error"):
                    result["speaker_error"] = save_res["error"]
                else:
                    result["speaker_inserted"] = save_res.get("inserted", 0)
            except Exception as e:
                result["speaker_error"] = str(e)

        return result

    def _search_speaker_vector(
        self,
        *,
        speaker_vector: list[float],
        top_k: int = 1,
        user_id: str | None = None,
        threshold: float | None = None,
    ) -> dict | None:
        q_filter = None
        if user_id:
            q_filter = Filter(
                should=[
                    FieldCondition(key="user_id", match=MatchValue(value=user_id)),
                ]
            )

        hits = self._client.search(
            collection_name=self._speaker_collection_name,
            query_vector=speaker_vector,
            limit=top_k,
            query_filter=q_filter,
            search_params=SearchParams(hnsw_ef=128),
            score_threshold=threshold,
            with_payload=True,
            with_vectors=True,
        )

        results: list[dict] = []
        for h in hits or []:
            payload = h.payload or {}

            uid = payload.get("user_id")
            if uid is None:
                uid = (payload.get("metadata") or {}).get("user_id")

            vec = None
            hv = getattr(h, "vector", None)
            if isinstance(hv, dict):
                if hv:
                    vec = next(iter(hv.values()))
            else:
                vec = hv

            results.append(
                {
                    "user_id": uid,
                    "vector": vec,
                    "id": str(h.id),
                    "score": float(h.score),
                }
            )

        return results[0] if results else None

    def initialize(self) -> None:
        # get config
        config = os.getenv("PERONA_VDB_CONFIG", "{}")
        config = json.loads(config)
        self._profiler_collection_name = config.get("profiler_collection_name", None)
        self._speaker_collection_name = config.get("speaker_collection_name", None)

        # init client
        self._client = get_qdrant_client(**config)

        # init profiler
        self._profiler_embeddings = get_embedding_model(**config)
        self._ensure_collection(
            self._profiler_collection_name,
            len(self._profiler_embeddings.embed_query("dimension-probe")),
        )
        self._profiler_vector_store = QdrantVectorStore(
            client=self._client,
            collection_name=self._profiler_collection_name,
            embedding=self._profiler_embeddings,
        )

        # init speaker vector
        self._ensure_collection(
            self._speaker_collection_name,
            MODEL_CONFIG[SpeakerVectorRunner.MODEL_TYPE].embedding_dim,
        )

    def run(self, data: bytes) -> bytes | None:
        json_data = json.loads(data)

        match json_data["op"]:
            case VectorRunnerOP.load:
                result = self._load(**json_data["param"])
                return json.dumps(result).encode()
            case VectorRunnerOP.save:
                result = self._save(**json_data["param"])
                return json.dumps(result).encode()
            case VectorRunnerOP.search_speaker_vector:
                result = self._search_speaker_vector(**json_data["param"])
                return json.dumps(result).encode() if result is not None else result
            case _:
                return None
