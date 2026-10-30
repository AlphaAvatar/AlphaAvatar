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
from threading import RLock
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    SearchParams,
    VectorParams,
)

from alphaavatar.agents.avatar.provider.enums import ProviderKind
from alphaavatar.agents.avatar.provider.factory import create_embedding_model
from alphaavatar.agents.avatar.provider.schemas import ProviderTaskConfig
from alphaavatar.agents.persona.enums import VectorRunnerOP
from alphaavatar.agents.runtime.inference import InferenceRunner
from alphaavatar.agents.utils.vdb import qdrant

from ...processors.face.analysis_runner import FaceAnalysisRunner
from ...processors.face.model_files import FACE_MODEL_CONFIG
from ...processors.speaker.model_files import SPEAKER_MODEL_CONFIG
from ...processors.speaker.vector_runner import SpeakerVectorRunner
from ...profile.serialization import merge_profile_items


class QdrantRunner(InferenceRunner):
    INFERENCE_METHOD = "alphaavatar.persona.vdb.qdrant"

    def __init__(self):
        super().__init__()
        self._user_locks: dict[str, RLock] = {}

    def _ensure_collection(self, collection_name, embedding_dim) -> None:
        """Create collection if missing; infer embedding dimension dynamically (sync)."""
        try:
            self._client.get_collection(collection_name)
            return
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
        spk_filter = Filter(should=[FieldCondition(key="user_id", match=MatchValue(value=user_id))])
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

        # 3) Load face vector from face collection
        face_vector = None
        face_filter = Filter(
            should=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
        )
        face_points = self._scroll_all(face_filter, self._face_collection_name, with_vectors=True)
        if face_points:
            p = face_points[0]
            hv = getattr(p, "vector", None)
            if isinstance(hv, dict):
                if hv:
                    face_vector = next(iter(hv.values()))
            else:
                face_vector = hv

        return {
            "details_items": details_items,
            "speaker_vector": speaker_vector,
            "face_vector": face_vector,
        }

    def _save(self, *, user_id: str, **updates) -> dict:
        with self._user_locks.setdefault(user_id, RLock()):
            return self._save_user(user_id=user_id, **updates)

    def _save_user(
        self,
        *,
        user_id: str,
        details_items: list[dict] | None,
        speaker_vector: list[float] | None,
        face_vector: list[float] | None = None,
    ) -> dict:
        # Stable field IDs make retries idempotent and preserve unrelated fields.
        if details_items:
            normalized = []
            for item in details_items:
                metadata = dict(item.get("metadata") or {})
                metadata["user_id"] = user_id
                normalized.append({**item, "metadata": metadata})
            normalized = merge_profile_items(
                self._load(user_id=user_id)["details_items"], normalized
            )
            if normalized:
                self._profiler_vector_store.add_texts(
                    [item["page_content"] for item in normalized],
                    [item["metadata"] for item in normalized],
                    [item["id"] for item in normalized],
                )
        for kind, vector, collection in (
            ("speaker", speaker_vector, self._speaker_collection_name),
            ("face", face_vector, self._face_collection_name),
        ):
            if vector is None:
                continue
            filt = Filter(must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))])
            existing = self._scroll_all(filt, collection)
            ids = [point.id for point in existing] or [
                str(uuid5(NAMESPACE_URL, f"{kind}:{user_id}"))
            ]
            self._client.upsert(
                collection_name=collection,
                points=[
                    PointStruct(id=key, vector=vector, payload={"user_id": user_id}) for key in ids
                ],
                wait=True,
            )
        return {"user_id": user_id, "inserted": len(details_items or []), "error": None}

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
                should=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
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

            user_id = payload.get("user_id")
            if user_id is None:
                user_id = (payload.get("metadata") or {}).get("user_id")

            vec = None
            hv = getattr(h, "vector", None)
            if isinstance(hv, dict):
                if hv:
                    vec = next(iter(hv.values()))
            else:
                vec = hv

            results.append(
                {"user_id": user_id, "vector": vec, "id": str(h.id), "score": float(h.score)}
            )

        return results[0] if results else None

    def _search_face_vector(
        self,
        *,
        face_vector: list[float],
        top_k: int = 1,
        user_id: str | None = None,
        threshold: float | None = None,
    ) -> dict | None:
        q_filter = None
        if user_id:
            q_filter = Filter(
                should=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
            )

        hits = self._client.search(
            collection_name=self._face_collection_name,
            query_vector=face_vector,
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

            user_id = payload.get("user_id")
            if user_id is None:
                user_id = (payload.get("metadata") or {}).get("user_id")

            vec = None
            hv = getattr(h, "vector", None)
            if isinstance(hv, dict):
                if hv:
                    vec = next(iter(hv.values()))
            else:
                vec = hv

            results.append(
                {"user_id": user_id, "vector": vec, "id": str(h.id), "score": float(h.score)}
            )

        return results[0] if results else None

    #
    # Runner Interface
    #

    def _get_vdb_config(self, config: dict[str, Any]) -> dict[str, Any]:
        vdb_config = dict(config)
        vdb_config.pop("embedding", None)
        return vdb_config

    def _get_profiler_embeddings(self, config: dict[str, Any]):
        embedding_config = config.get("embedding")

        if not embedding_config:
            raise ValueError("`embedding` is required in PERSONA_VDB_CONFIG")

        provider = embedding_config.get("provider")
        model = embedding_config.get("model")
        extra = embedding_config.get("extra") or {}

        if not provider:
            raise ValueError("`embedding.provider` is required in PERSONA_VDB_CONFIG")
        if not model:
            raise ValueError("`embedding.model` is required in PERSONA_VDB_CONFIG")

        task_config = ProviderTaskConfig(
            kind=ProviderKind.EMBEDDING, provider=provider, model=model, extra=extra
        )

        return create_embedding_model(task_config)

    def initialize(self) -> None:
        from langchain_qdrant import QdrantVectorStore

        # get config
        config = os.getenv("PERSONA_VDB_CONFIG", "{}")
        config = json.loads(config)

        self._profiler_collection_name = config.get("profiler_collection_name", None)
        self._speaker_collection_name = config.get("speaker_collection_name", None)
        self._face_collection_name = config.get("face_collection_name", None)

        if not self._profiler_collection_name:
            raise ValueError("`profiler_collection_name` is required in PERSONA_VDB_CONFIG")
        if not self._speaker_collection_name:
            raise ValueError("`speaker_collection_name` is required in PERSONA_VDB_CONFIG")
        if not self._face_collection_name:
            self._face_collection_name = f"{self._speaker_collection_name}_face"

        # init client
        self._client = qdrant.get_client(**self._get_vdb_config(config))

        # init profiler
        self._profiler_embeddings = self._get_profiler_embeddings(config)
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
            SPEAKER_MODEL_CONFIG[SpeakerVectorRunner.MODEL_TYPE].embedding_dim,
        )

        # init face vector
        self._ensure_collection(
            self._face_collection_name,
            FACE_MODEL_CONFIG[FaceAnalysisRunner.MODEL_TYPE].embedding_dim,
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
            case VectorRunnerOP.search_face_vector:
                result = self._search_face_vector(**json_data["param"])
                return json.dumps(result).encode() if result is not None else result
            case _:
                return None
