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

from copy import deepcopy
from typing import Any

from langchain_community.vectorstores import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from alphaavatar.agents.persona import ProfilerBase

from .enum.user_profile import UserProfile
from .profiler_op import (
    ProfileDelta,
    append_string,
    clear_path,
    parse_pointer,
    post_fix_conflicts,
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
    Orchestrates:
      - LLM delta extraction
      - Applying patch ops to a UserProfile
      - Persisting to / loading from a vector store (one vector per item)
    """

    def __init__(
        self,
        persist_dir: str = "./chroma_profile",
        collection: str = "user_profiles",
        chat_model: str = "gpt-4o-mini",
        embedding_model: str = "text-embedding-3-small",
        temperature: float = 0.0,
    ) -> None:
        super().__init__()
        self.persist_dir = persist_dir
        # os.makedirs(self.persist_dir, exist_ok=True)

        # LLM
        self.llm = ChatOpenAI(model=chat_model, temperature=temperature)
        self._delta_llm = self.llm.with_structured_output(ProfileDelta)

        # Embeddings + Vector store
        self.embeddings = OpenAIEmbeddings(model=embedding_model)
        self.vs = Chroma(
            collection_name=collection,
            embedding_function=self.embeddings,
            persist_directory=self.persist_dir,
        )

    def update(self, profile: UserProfile, new_turn: str) -> UserProfile:
        """
        Generate a delta from the new dialog turn and apply it to the given profile.
        Returns a new (updated) UserProfile instance.
        """
        delta = self._extract_delta(profile, new_turn)
        updated = self._apply_patch(profile, delta)
        return updated

    def save(self, user_id: str, profile: UserProfile) -> None:
        """
        Persist the profile to the vector store as one embedding per item.
        Strategy: delete all existing items for this user_id, then upsert current snapshot.
        """
        # Remove existing entries for this user
        try:
            # Use underlying Chroma collection for filtered delete
            self.vs._collection.delete(where={"user_id": user_id})  # type: ignore[attr-defined]
        except Exception:
            # Fallback: ignore if unavailable
            pass

        profile.model_dump()
        # items = flatten_items(user_id, data)
        items = []

        if not items:
            self.vs.persist()
            return

        texts = [it["page_content"] for it in items]
        metadatas = [it["metadata"] for it in items]
        ids = [it["id"] for it in items]

        # Upsert items (Chroma add_texts will overwrite if IDs exist)
        self.vs.add_texts(texts=texts, metadatas=metadatas, ids=ids)
        self.vs.persist()

    def load(self, user_id: str) -> UserProfile:
        """
        Load a full UserProfile from the vector store (all items for this user_id).
        """
        try:
            raw = self.vs._collection.get(  # type: ignore[attr-defined]
                where={"user_id": user_id}, include=["metadatas", "documents", "ids"]
            )
        except Exception:
            # If the wrapper doesn't support filtered get, fallback to empty
            raw = {"metadatas": [], "documents": [], "ids": []}

        metadatas = raw.get("metadatas", []) or []
        documents = raw.get("documents", []) or []
        ids = raw.get("ids", []) or []

        items = []
        for meta, doc, _id in zip(metadatas, documents, ids, strict=False):
            # Ensure required keys exist
            meta = meta or {}
            meta.setdefault("path", "")
            meta.setdefault("type", "scalar")
            meta.setdefault("json_value", None)
            items.append(
                {
                    "id": _id,
                    "page_content": doc,
                    "metadata": meta,
                }
            )

        # data = rebuild_from_items(items)
        data = {}
        return UserProfile(**data)

    def _extract_delta(self, profile: UserProfile, new_turn: str) -> ProfileDelta:
        """Ask the LLM to generate patch ops relative to the current profile."""
        return (DELTA_PROMPT | self._delta_llm).invoke(
            {"current_profile": profile.model_dump_json(), "new_turn": new_turn}
        )

    def _apply_patch(self, profile: UserProfile, delta: ProfileDelta) -> UserProfile:
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
