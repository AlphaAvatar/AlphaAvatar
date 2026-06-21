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
from uuid import uuid4

from livekit.agents.inference_runner import _InferenceRunner

from alphaavatar.agents.persona import VectorRunnerOP
from alphaavatar.agents.providers import ProviderKind, ProviderTaskConfig
from alphaavatar.agents.providers.embedding import create_embedding_model
from alphaavatar.agents.utils.vdb import lancedb

from ..models import FACE_MODEL_CONFIG, SPEAKER_MODEL_CONFIG
from .face_analysis_runner import FaceAnalysisRunner
from .speaker_vector_runner import SpeakerVectorRunner


class LanceDBRunner(_InferenceRunner):
    INFERENCE_METHOD = "alphaavatar_persona_lancedb"

    def __init__(self):
        super().__init__()

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
            "ts": metadata.get("ts", ""),
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
        metadata.setdefault("ts", row.get("ts", ""))
        metadata.setdefault("entities", row.get("entities", []))

        return {
            "id": str(row.get("id", "")),
            "page_content": row.get("page_content", ""),
            "metadata": metadata,
        }

    #
    # speaker_vector <-> Lance rows
    #
    def _speaker_to_row(
        self, *, user_id: str, vector: list[float], row_id: str | None = None
    ) -> dict:
        return {
            "id": str(row_id or uuid4()),
            "user_id": str(user_id),
            "vector": vector,
        }

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
    def _face_to_row(self, *, user_id: str, vector: list[float], row_id: str | None = None) -> dict:
        return {
            "id": str(row_id or uuid4()),
            "user_id": str(user_id),
            "vector": vector,
        }

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

    def _load(self, *, user_id: str, **kwargs) -> dict:
        # 1) load details_items
        details_items: list[dict[str, Any]] = []

        try:
            rows = self._profiler_table.search().where(f"user_id = '{user_id}'").to_list()
        except Exception:
            # Some versions of LanceDB have incomplete where/search support, so we fall back to full table filtering
            rows = [
                r for r in self._profiler_table.to_list() if str(r.get("user_id", "")) == user_id
            ]

        for row in rows:
            details_items.append(self._details_row_to_item(row))

        # 2) load speaker_vector
        speaker_vector = None
        try:
            spk_rows = (
                self._speaker_table.search().where(f"user_id = '{user_id}'").limit(1).to_list()
            )
        except Exception:
            spk_rows = [
                r for r in self._speaker_table.to_list() if str(r.get("user_id", "")) == user_id
            ][:1]

        if spk_rows:
            speaker_vector = spk_rows[0].get("vector")

        # 3) load face_vector
        face_vector = None
        try:
            face_rows = self._face_table.search().where(f"user_id = '{user_id}'").limit(1).to_list()
        except Exception:
            face_rows = [
                r for r in self._face_table.to_list() if str(r.get("user_id", "")) == user_id
            ][:1]

        if face_rows:
            face_vector = face_rows[0].get("vector")

        return {
            "details_items": details_items,
            "speaker_vector": speaker_vector,
            "face_vector": face_vector,
        }

    def _save(
        self,
        *,
        user_id: str,
        details_items: list[dict] | None,
        speaker_vector: list[float] | None,
        face_vector: list[float] | None = None,
    ) -> dict:
        result = {
            "user_id": user_id,
            "deleted": False,
            "inserted": 0,
            "error": None,
            "speaker_deleted": False,
            "speaker_inserted": 0,
            "speaker_error": None,
            "face_deleted": False,
            "face_inserted": 0,
            "face_error": None,
        }

        # 1) save details_items
        if details_items:
            try:
                # First, delete the old data for this user_id, keeping it consistent with the Qdrant version: full group replacement
                try:
                    self._profiler_table.delete(f"user_id = '{user_id}'")
                except Exception:
                    old_rows = [
                        r
                        for r in self._profiler_table.to_list()
                        if str(r.get("user_id", "")) == user_id
                    ]
                    old_ids = [str(r["id"]) for r in old_rows if "id" in r]
                    if old_ids:
                        quoted_ids = ",".join(f"'{x}'" for x in old_ids)
                        self._profiler_table.delete(f"id IN ({quoted_ids})")

                result["deleted"] = True

                texts = [it.get("page_content", "") for it in details_items]

                # As a fallback to prevent missing metadata fields
                normalized_items = []
                for it in details_items:
                    metadata = dict(it.get("metadata", {}) or {})
                    metadata["user_id"] = user_id
                    normalized_items.append(
                        {
                            "id": str(it.get("id") or uuid4()),
                            "page_content": it.get("page_content", ""),
                            "metadata": metadata,
                        }
                    )

                vectors = self._profiler_embeddings.embed_documents(texts)
                rows = [
                    self._details_to_row(item, vector)
                    for item, vector in zip(normalized_items, vectors, strict=True)
                ]

                self._profiler_table.add(rows)
                result["inserted"] = len(rows)

            except Exception as e:
                result["error"] = str(e)

        # 2) save speaker_vector
        if speaker_vector:
            try:
                try:
                    self._speaker_table.delete(f"user_id = '{user_id}'")
                except Exception:
                    old_rows = [
                        r
                        for r in self._speaker_table.to_list()
                        if str(r.get("user_id", "")) == user_id
                    ]
                    old_ids = [str(r["id"]) for r in old_rows if "id" in r]
                    if old_ids:
                        quoted_ids = ",".join(f"'{x}'" for x in old_ids)
                        self._speaker_table.delete(f"id IN ({quoted_ids})")

                result["speaker_deleted"] = True

                row = self._speaker_to_row(user_id=user_id, vector=speaker_vector)
                self._speaker_table.add([row])
                result["speaker_inserted"] = 1

            except Exception as e:
                result["speaker_error"] = str(e)

        # 3) save face_vector
        if face_vector:
            try:
                try:
                    self._face_table.delete(f"user_id = '{user_id}'")
                except Exception:
                    old_rows = [
                        r
                        for r in self._face_table.to_list()
                        if str(r.get("user_id", "")) == user_id
                    ]
                    old_ids = [str(r["id"]) for r in old_rows if "id" in r]
                    if old_ids:
                        quoted_ids = ",".join(f"'{x}'" for x in old_ids)
                        self._face_table.delete(f"id IN ({quoted_ids})")

                result["face_deleted"] = True

                row = self._face_to_row(user_id=user_id, vector=face_vector)
                self._face_table.add([row])
                result["face_inserted"] = 1

            except Exception as e:
                result["face_error"] = str(e)

        return result

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
            kind=ProviderKind.EMBEDDING,
            provider=provider,
            model=model,
            extra=extra,
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
        self._client = lancedb.get_client(**self._get_vdb_config(config))

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
                "ts": "",
                "entities": ["__init__"],
                "raw_metadata": "{}",
            }
        ]
        self._ensure_table(self._profiler_collection_name, profiler_seed)
        self._profiler_table = self._client.open_table(self._profiler_collection_name)

        # init speaker table
        speaker_dim = SPEAKER_MODEL_CONFIG[SpeakerVectorRunner.MODEL_TYPE].embedding_dim
        speaker_seed = [
            {
                "id": "__init__",
                "user_id": "",
                "vector": [0.0] * speaker_dim,
            }
        ]
        self._ensure_table(self._speaker_collection_name, speaker_seed)
        self._speaker_table = self._client.open_table(self._speaker_collection_name)

        # init face table
        face_dim = FACE_MODEL_CONFIG[FaceAnalysisRunner.MODEL_TYPE].embedding_dim
        face_seed = [
            {
                "id": "__init__",
                "user_id": "",
                "vector": [0.0] * face_dim,
            }
        ]
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
