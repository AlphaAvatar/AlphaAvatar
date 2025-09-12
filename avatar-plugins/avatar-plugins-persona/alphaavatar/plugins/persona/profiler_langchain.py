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
from __future__ import annotations

import asyncio
import os
import shutil
from copy import deepcopy
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    VectorParams,
)

from alphaavatar.agents.persona import PersonaCache, ProfilerBase, UserProfileBase

from .enum.user_profile import UserProfile
from .profiler_op import (
    ProfileDelta,
    append_string,
    clear_path,
    flatten_items,
    parse_pointer,
    post_fix_conflicts,
    rebuild_from_items,
    remove_string,
    write_set,
)

DELTA_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a "profile delta extractor". Compare the NEW TURN to the CURRENT PROFILE and output only CHANGES as PatchOps.
Rules:
- Use JSON Pointer-like paths (e.g., "/preferences/interests", "/device/os", "/personality/traits").
- For lists of strings (e.g., interests/dislikes/traits/constraints/brands):
    * op=append to add a single string (avoid duplicates)
    * op=remove to remove a single string
    * op=set ONLY if replacing the entire list (value must be a list)
- For structured nested objects (e.g., location, employment):
    * Prefer op=set on the specific field path (e.g., "/location/country", "/employment/job_title")
- Use op=clear only when the user explicitly invalidates prior info.
- evidence must quote the original sentence or a tight paraphrase; set confidence in [0,1].
- If nothing changes, return an empty list.
Avoid hallucinations. Do not invent values not clearly stated or strongly implied.
""",
        ),
        (
            "human",
            "CURRENT PROFILE (JSON):\n{current_profile}\n\nNEW TURN:\n{new_turn}\n\nOutput only ProfileDelta (list of PatchOps).",
        ),
    ]
)


class ProfilerLangChain(ProfilerBase):
    """
    Qdrant-backed pipeline:
      - async LLM delta extraction
      - sync in-memory patch
      - async persistence via Qdrant
    """

    def __init__(
        self,
        *,
        collection: str = "alphaavatar_user_profiles",
        chat_model: str = "gpt-4o-mini",
        embedding_model: str = "text-embedding-3-small",
        temperature: float = 0.0,
        host: str | None = None,
        port: int | None = None,
        path: str = "/tmp/qdrant",
        url: str | None = None,
        api_key: str | None = None,
        on_disk: bool = False,
        prefer_grpc: bool = False,
    ) -> None:
        super().__init__()
        self.collection = collection
        self.llm = ChatOpenAI(model=chat_model, temperature=temperature)
        self._delta_llm = self.llm.with_structured_output(ProfileDelta)
        self.embeddings = OpenAIEmbeddings(model=embedding_model)
        self.__post_init__(
            host=host,
            port=port,
            path=path,
            url=url,
            api_key=api_key,
            on_disk=on_disk,
            prefer_grpc=prefer_grpc,
        )

    def __post_init__(
        self,
        *,
        host: str | None,
        port: int | None,
        path: str,
        url: str | None,
        api_key: str | None,
        on_disk: bool,
        prefer_grpc,
    ):
        """
        Initialize the Qdrant vector store.

        Args:
            collection_name (str): Name of the collection.
            embedding_model_dims (int): Dimensions of the embedding model.
            client (QdrantClient, optional): Existing Qdrant client instance. Defaults to None.
            host (str, optional): Host address for Qdrant server. Defaults to None.
            port (int, optional): Port for Qdrant server. Defaults to None.
            path (str, optional): Path for local Qdrant database. Defaults to None.
            url (str, optional): Full URL for Qdrant server. Defaults to None.
            api_key (str, optional): API key for Qdrant server. Defaults to None.
            on_disk (bool, optional): Enables persistent storage. Defaults to False.
        """
        is_remote = bool(url) or bool(api_key) or (host and port)

        if is_remote:
            self.client = QdrantClient(
                url=url if url else None,
                host=host if host else None,
                port=port if port else None,
                api_key=api_key if api_key else None,
                prefer_grpc=prefer_grpc,
            )
        else:
            if not on_disk and os.path.isdir(path):
                shutil.rmtree(path)
            self.client = QdrantClient(path=path, prefer_grpc=False)

        self._ensure_collection()
        self.vs = QdrantVectorStore(
            client=self.client,
            collection_name=self.collection,
            embedding=self.embeddings,
        )

    def _ensure_collection(self) -> None:
        """Create collection if missing; infer embedding dimension dynamically (sync)."""
        try:
            self.client.get_collection(self.collection)
            return  # exists
        except Exception:
            pass

        dim = len(self.embeddings.embed_query("dimension-probe"))
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )

    def load(self, user_id: str) -> UserProfile:
        """Fetch all points for user_id via Scroll API, rebuild profile (synchronous)."""

        filt = Filter(must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))])
        all_points = []
        next_offset = None

        while True:
            try:
                points, next_offset = self.client.scroll(
                    collection_name=self.collection,
                    limit=256,
                    with_payload=True,
                    with_vectors=False,
                    scroll_filter=filt,
                    offset=next_offset,
                )
            except TypeError:
                # Some client versions use `filter` instead of `scroll_filter`
                points, next_offset = self.client.scroll(
                    collection_name=self.collection,
                    limit=256,
                    with_payload=True,
                    with_vectors=False,
                    filter=filt,
                    offset=next_offset,
                )

            all_points.extend(points or [])
            if not next_offset or not points:
                break

        items: list[dict[str, Any]] = []
        for p in all_points:
            payload = p.payload or {}
            doc = payload.get("page_content") or ""
            meta = {k: v for k, v in payload.items() if k != "page_content"}
            meta.setdefault("path", "")
            meta.setdefault("type", "scalar")
            meta.setdefault("json_value", None)

            items.append({"id": str(p.id), "page_content": doc, "metadata": meta})

        data = rebuild_from_items(items)
        return UserProfile(**data)

    async def update(self, perona: PersonaCache):
        """Async delta extraction -> in-memory patch."""
        profile = perona.user_profile
        chat_context = perona.messages

        new_turn = UserProfile.apply_update_template(chat_context)
        delta = await self._aextract_delta(profile, new_turn)
        profile = self._apply_patch(profile, delta)

        perona.user_profile = profile

    async def save(self, user_id: str, profile: UserProfileBase | UserProfile) -> None:
        """Async: delete old by user_id filter, then upsert all items."""

        # 1) delete existing points for this user_id
        async def _delete_by_filter():
            filt = Filter(must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))])
            self.client.delete(
                collection_name=self.collection,
                points_selector=FilterSelector(filter=filt),
                wait=True,
            )

        await asyncio.to_thread(_delete_by_filter)

        # 2) flatten and add
        data = profile.model_dump()
        items = flatten_items(user_id, data)
        if not items:
            return

        texts = [it["page_content"] for it in items]
        metadatas = [it["metadata"] for it in items]
        ids = [it["id"] for it in items]

        await asyncio.to_thread(self.vs.add_texts, texts, metadatas, ids)

    async def _aextract_delta(
        self, profile: UserProfileBase | UserProfile, new_turn: str
    ) -> ProfileDelta:
        """Ask the LLM to generate patch ops relative to the current profile."""
        chain = DELTA_PROMPT | self._delta_llm
        return await chain.ainvoke(
            {"current_profile": profile.model_dump_json(), "new_turn": new_turn}  # type: ignore
        )

    def _apply_patch(
        self, profile: UserProfileBase | UserProfile, delta: ProfileDelta
    ) -> UserProfile:
        """
        Apply PatchOps to a UserProfile:
          - set: overwrite value (scalar/list/object) at path
          - append/remove: operate on string lists
          - clear: clear path (None or [])
        """
        data: dict[str, Any] = deepcopy(profile.model_dump())

        for op in delta.ops:
            tokens = parse_pointer(op.path)
            if not tokens:
                continue
            try:
                if op.op == "set":
                    write_set(data, tokens, op.value)
                elif op.op == "clear":
                    clear_path(data, tokens)
                elif op.op == "append" and op.value is not None:
                    append_string(data, tokens, op.value)
                elif op.op == "remove" and op.value is not None:
                    remove_string(data, tokens, op.value)
            except Exception:
                # In production: log the error with op details
                continue

        post_fix_conflicts(data)
        return UserProfile(**data)
