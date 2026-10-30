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
from uuid import NAMESPACE_URL, uuid4, uuid5

from alphaavatar.agents.avatar.provider.enums import ProviderKind
from alphaavatar.agents.avatar.provider.factory import create_embedding_model
from alphaavatar.agents.avatar.provider.schemas import ProviderTaskConfig
from alphaavatar.agents.persona.enums import VectorRunnerOP
from alphaavatar.agents.runtime.inference import InferenceRunner
from alphaavatar.agents.runtime.plugin import AvatarModule
from alphaavatar.agents.utils.vdb import lancedb
from alphaavatar.core.workspace import WorkspacePaths

from ...processors.face.analysis_runner import FaceAnalysisRunner
from ...processors.face.model_files import FACE_MODEL_CONFIG
from ...processors.speaker.model_files import SPEAKER_MODEL_CONFIG
from ...processors.speaker.vector_runner import SpeakerVectorRunner
from ...profile.serialization import merge_profile_items


class LanceDBRunner(InferenceRunner):
    INFERENCE_METHOD = "alphaavatar.persona.vdb.lancedb"

    def __init__(self):
        super().__init__()
        self._user_locks: dict[str, RLock] = {}

    def _ensure_table(self, table_name: str, seed_rows: list[dict]) -> None:
        if self._client.table_exists(table_name):
            return

        table = self._client.create_table(table_name, seed_rows)
        table.delete("id = '__init__'")

    def _normalize_str_list(self, value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(x) for x in value if x is not None]
        if isinstance(value, tuple):
            return [str(x) for x in value if x is not None]
        return [str(value)]

    #
    # details_items <-> Lance rows
    #

    def _details_to_row(self, item: dict, vector: list[float]) -> dict:
        metadata = item.get("metadata", {}) or {}
        return {
            "id": str(item.get("id") or uuid4()),
            "vector": vector,
            "page_content": item.get("page_content", ""),
            "user_id": str(metadata.get("user_id", "")),
            "topic": metadata.get("topic", ""),
            "updated_at": metadata.get("updated_at", ""),
            "entities": self._normalize_str_list(metadata.get("entities")),
            "raw_metadata": json.dumps(metadata, ensure_ascii=False),
        }

    def _details_row_to_item(self, row: dict) -> dict:
        raw_metadata = row.get("raw_metadata", "")
        metadata = {}
        if raw_metadata:
            try:
                metadata = json.loads(raw_metadata)
            except Exception:
                metadata = {}

        # As a fallback to prevent missing metadata fields
        metadata.setdefault("user_id", row.get("user_id", ""))
        metadata.setdefault("topic", row.get("topic", ""))
        metadata.setdefault("updated_at", row.get("updated_at", ""))
        metadata.setdefault("entities", row.get("entities", []))

        return {
            "id": str(row.get("id", "")),
            "page_content": row.get("page_content", ""),
            "metadata": metadata,
        }

    #
    # speaker_vector <-> Lance rows
    #

    def _speaker_row_to_result(self, row: dict) -> dict:
        distance = float(row.get("_distance", float("inf")))

        # LanceDB cosine distance: smaller is more similar.
        # Convert it to cosine-similarity-like score so it matches Qdrant's COSINE score style.
        score = 1.0 - distance
        score = max(-1.0, min(1.0, score))

        return {
            "user_id": str(row.get("user_id", "")),
            "vector": row.get("vector"),
            "id": str(row.get("id", "")),
            "distance": distance,
            "score": score,
        }

    #
    # face_vector <-> Lance rows
    #

    def _face_row_to_result(self, row: dict) -> dict:
        distance = float(row.get("_distance", float("inf")))

        # LanceDB cosine distance: smaller is more similar.
        # Convert it to cosine-similarity-like score so it matches Qdrant's COSINE score style.
        score = 1.0 - distance
        score = max(-1.0, min(1.0, score))

        return {
            "user_id": str(row.get("user_id", "")),
            "vector": row.get("vector"),
            "id": str(row.get("id", "")),
            "distance": distance,
            "score": score,
        }

    #
    # LanceDB Operations
    #

    @staticmethod
    def _user_filter(user_id: str) -> str:
        if not isinstance(user_id, str) or not user_id or "\0" in user_id:
            raise ValueError("Invalid user identifier")
        return "user_id = '" + user_id.replace("'", "''") + "'"

    def _load(self, *, user_id: str, **kwargs) -> dict:
        predicate = self._user_filter(user_id)
        details = self._profiler_table.search().where(predicate).limit(None).to_list()
        speakers = self._speaker_table.search().where(predicate).limit(1).to_list()
        faces = self._face_table.search().where(predicate).limit(1).to_list()
        return {
            "details_items": [self._details_row_to_item(row) for row in details],
            "speaker_vector": speakers[0].get("vector") if speakers else None,
            "face_vector": faces[0].get("vector") if faces else None,
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
        self._user_filter(user_id)
        if details_items:
            normalized = []
            for item in details_items:
                metadata = dict(item.get("metadata") or {})
                metadata["user_id"] = user_id
                normalized.append({**item, "metadata": metadata})
            normalized = merge_profile_items(
                self._load(user_id=user_id)["details_items"], normalized
            )
            vectors = (
                self._profiler_embeddings.embed_documents(
                    [item.get("page_content", "") for item in normalized]
                )
                if normalized
                else []
            )
            rows = [
                self._details_to_row(item, vector)
                for item, vector in zip(normalized, vectors, strict=True)
            ]
            # The backend commits a field update atomically; there is no delete/insert gap.
            if rows:
                (
                    self._profiler_table.merge_insert("id")
                    .when_matched_update_all(where="source.updated_at >= target.updated_at")
                    .when_not_matched_insert_all()
                    .execute(rows)
                )
        for kind, table, vector in (
            ("speaker", self._speaker_table, speaker_vector),
            ("face", self._face_table, face_vector),
        ):
            if vector is None:
                continue
            row = {
                "id": str(uuid5(NAMESPACE_URL, f"{kind}:{user_id}")),
                "user_id": user_id,
                "vector": vector,
            }
            (
                table.merge_insert("user_id")
                .when_matched_update_all()
                .when_not_matched_insert_all()
                .execute([row])
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
        """
        LanceDB typically returns `_distance`, with smaller values ​​indicating greater similarity.
        Here's how to handle compatibility:
        - First, perform a vector search
        - Then, filter by `user_id` on the Python side
        - If a `threshold` is provided, filter by the converted score
        """
        try:
            all_count = self._speaker_table.count_rows()
            if all_count == 0:
                return None

            fetch_k = min(max(top_k * 8, 32), all_count)

            try:
                query = self._speaker_table.search(speaker_vector)
                try:
                    query = query.metric("cosine")
                except Exception:
                    pass

                rows = query.limit(fetch_k).to_list()
            except Exception:
                rows = []

            results: list[dict] = []
            for row in rows:
                row_user_id = str(row.get("user_id", ""))

                if user_id and row_user_id != user_id:
                    continue

                item = self._speaker_row_to_result(row)

                if threshold is not None and item["score"] < threshold:
                    continue

                results.append(item)
                if len(results) >= top_k:
                    break

            return results[0] if results else None

        except Exception:
            return None

    def _search_face_vector(
        self,
        *,
        face_vector: list[float],
        top_k: int = 1,
        user_id: str | None = None,
        threshold: float | None = None,
    ) -> dict | None:
        """
        LanceDB typically returns `_distance`, with smaller values indicating greater similarity.
        Here's how to handle compatibility:
        - First, perform a vector search
        - Then, filter by `user_id` on the Python side
        - If a `threshold` is provided, filter by the converted score
        """
        try:
            all_count = self._face_table.count_rows()
            if all_count == 0:
                return None

            fetch_k = min(max(top_k * 8, 32), all_count)

            try:
                query = self._face_table.search(face_vector)
                try:
                    query = query.metric("cosine")
                except Exception:
                    pass

                rows = query.limit(fetch_k).to_list()
            except Exception:
                rows = []

            results: list[dict] = []
            for row in rows:
                row_user_id = str(row.get("user_id", ""))

                if user_id and row_user_id != user_id:
                    continue

                item = self._face_row_to_result(row)

                if threshold is not None and item["score"] < threshold:
                    continue

                results.append(item)
                if len(results) >= top_k:
                    break

            return results[0] if results else None

        except Exception:
            return None

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
        # get config
        config = os.getenv("PERSONA_VDB_CONFIG", "{}")
        config = json.loads(config)

        self._profiler_collection_name = config.get("profiler_collection_name")
        self._speaker_collection_name = config.get("speaker_collection_name")
        self._face_collection_name = config.get("face_collection_name")

        if not self._profiler_collection_name:
            raise ValueError("`profiler_collection_name` is required in PERSONA_VDB_CONFIG")
        if not self._speaker_collection_name:
            raise ValueError("`speaker_collection_name` is required in PERSONA_VDB_CONFIG")
        if not self._face_collection_name:
            raise ValueError("`face_collection_name` is required in PERSONA_VDB_CONFIG")

        # init client
        vdb_config = self._get_vdb_config(config)
        if not vdb_config.get("client_path"):
            vdb_config["client_path"] = str(
                WorkspacePaths.from_root(self.launch.workspace_root)
                .data.indexes.namespace(AvatarModule.PERSONA.value)
                .backend("lancedb")
                .root
            )

        self._client = lancedb.get_client(**vdb_config)

        # init embeddings for details_items
        self._profiler_embeddings = self._get_profiler_embeddings(config)
        profiler_dim = len(self._profiler_embeddings.embed_query("dimension-probe"))

        # init profiler table
        profiler_seed = [
            {
                "id": "__init__",
                "vector": [0.0] * profiler_dim,
                "page_content": "__init__",
                "user_id": "",
                "topic": "",
                "updated_at": "",
                "entities": ["__init__"],
                "raw_metadata": "{}",
            }
        ]
        self._ensure_table(self._profiler_collection_name, profiler_seed)
        self._profiler_table = self._client.open_table(self._profiler_collection_name)

        # init speaker table
        speaker_dim = SPEAKER_MODEL_CONFIG[SpeakerVectorRunner.MODEL_TYPE].embedding_dim
        speaker_seed = [{"id": "__init__", "user_id": "", "vector": [0.0] * speaker_dim}]
        self._ensure_table(self._speaker_collection_name, speaker_seed)
        self._speaker_table = self._client.open_table(self._speaker_collection_name)

        # init face table
        face_dim = FACE_MODEL_CONFIG[FaceAnalysisRunner.MODEL_TYPE].embedding_dim
        face_seed = [{"id": "__init__", "user_id": "", "vector": [0.0] * face_dim}]
        self._ensure_table(self._face_collection_name, face_seed)
        self._face_table = self._client.open_table(self._face_collection_name)

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
