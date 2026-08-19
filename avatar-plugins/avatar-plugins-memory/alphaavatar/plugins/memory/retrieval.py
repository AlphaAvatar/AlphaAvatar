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
import json
from typing import Any

from livekit.agents.llm import ChatItem

from alphaavatar.agents.memory import (
    MemoryItem,
    MemoryPluginsTemplate,
    MemoryType,
    VectorRunnerOP,
)

from .log import logger
from .memory_op import LAYER_NOTE, merge_object_ids, rebuild_from_items


class MemoryRetrievalMixin:
    """Vector recall: by context, by graph node, and note candidates.

    Split out of MemoryRuntime for file size only; behaviour is unchanged.
    Requires from the host class: `inference_executor`, `vdb_inference_method`,
    `memory_cache`, `memory_recall_num`, `avatar_id`, `_pipeline_config`,
    `_note_consolidator`, and the four memory-bucket setters.
    """

    async def search_by_context(
        self,
        *,
        avatar_id: str,
        session_id: str,
        chat_context: list[ChatItem],
        timeout: float = 3,
    ) -> None:
        """Search for relevant memories based on the query."""
        context_str = MemoryPluginsTemplate.apply_search_template(
            chat_context[-getattr(self, "memory_search_context", 3) :],
            filter_roles=["system"],
        )

        if not context_str:
            # Without this line, "nothing in the log" means either success or
            # never-ran, and a missing recall cannot be told apart afterwards.
            logger.debug(
                "Memory [search_by_context] skipped: empty search context sid=%s", session_id
            )
            return

        json_data = {
            "op": VectorRunnerOP.search_by_context,
            "param": {
                "context_str": context_str,
                "object_ids": merge_object_ids(
                    [avatar_id],
                    self.memory_cache[session_id].object_ids,
                ),
                "top_k": self.memory_recall_num,
                "resolve_covered_items": self._pipeline_config.note.resolves_covered_items,
            },
        }

        result = await asyncio.wait_for(
            self.inference_executor.do_inference(
                self.vdb_inference_method,
                json.dumps(json_data).encode(),
            ),
            timeout=timeout,
        )

        if result is None:
            logger.warning("Memory [search_by_context] failed, result is None!")
            return

        data: dict[str, Any] = json.loads(result.decode())

        logger.debug(
            "Memory [search_by_context] sid=%s recalled=%d resolved=%d",
            session_id,
            int(data.get("recalled_count") or 0),
            len(data.get("memory_items") or []),
        )

        if data.get("memory_items"):
            memory_items = rebuild_from_items(data["memory_items"])

            # The candidate source for note maintenance may read this ledger,
            # and it must not read MemoryState: that view is capped and evicts
            # the oldest first -- precisely the records most likely to need an
            # update.
            self._note_consolidator.record_recall(memory_items)

            self.avatar_memory = [
                item for item in memory_items if item.memory_type == MemoryType.Avatar
            ]

            self.user_memory = [
                item for item in memory_items if item.memory_type == MemoryType.CONVERSATION
            ]

            self.tool_memory = [
                item for item in memory_items if item.memory_type == MemoryType.TOOLS
            ]

            self.env_memory = [item for item in memory_items if item.memory_type == MemoryType.ENV]

        if data.get("error"):
            logger.warning("Memory [search_by_context] err: %s", data["error"])

    async def search_by_graph_node(
        self,
        *,
        node_key: str | None = None,
        node_query: str | None = None,
        object_ids: list[str] | None = None,
        session_id: str | None = None,
        memory_type: str | None = None,
        node_type: str | None = None,
        max_hops: int = 0,
        top_k: int = 50,
        timeout: float = 3,
    ) -> list[MemoryItem]:
        node_keys: list[str] = []

        if node_key:
            lookup = self._graph_lookup()
            resolved = lookup.resolve_keys(node_key)

            if max_hops > 0:
                node_keys = lookup.expand_node_keys(
                    node_keys=resolved,
                    max_hops=max_hops,
                    max_neighbors_per_node=16,
                    min_weight=0.0,
                )
            else:
                node_keys = resolved

        json_data = {
            "op": VectorRunnerOP.search_by_graph_node,
            "param": {
                "node_keys": node_keys,
                "node_query": node_query,
                "object_ids": object_ids,
                "session_id": session_id,
                "memory_type": memory_type,
                "node_type": node_type,
                "top_k": top_k,
            },
        }

        result = await asyncio.wait_for(
            self.inference_executor.do_inference(
                self.vdb_inference_method,
                json.dumps(json_data).encode(),
            ),
            timeout=timeout,
        )

        if result is None:
            logger.warning("Memory [search_by_graph_node] failed, result is None!")
            return []

        data: dict[str, Any] = json.loads(result.decode())

        if data.get("error"):
            logger.warning("Memory [search_by_graph_node] err: %s", data["error"])
            return []

        return rebuild_from_items(data.get("memory_items") or [])

    async def _note_candidate_search(
        self,
        texts: list[str],
        *,
        object_ids: list[str],
        timeout: float = 5.0,
    ) -> list[list[dict[str, Any]]]:
        """Nearest existing notes for each incoming atomic memory.

        `object_ids` must be the owners the notes were written under -- the
        participants, not the avatar. Conversation memory is stored against the
        user, so filtering by avatar id alone intersects with nothing and the
        search silently returns no candidates at all.
        """
        empty: list[list[dict[str, Any]]] = [[] for _ in texts]

        if not texts:
            return []

        json_data = {
            "op": VectorRunnerOP.search_similar_batch,
            "param": {
                "texts": texts,
                "top_k": self._pipeline_config.maintenance.max_candidates_per_item,
                "object_ids": merge_object_ids(object_ids),
                "memory_type": MemoryType.CONVERSATION.value,
                "layer": LAYER_NOTE,
            },
        }

        try:
            result = await asyncio.wait_for(
                self.inference_executor.do_inference(
                    self.vdb_inference_method,
                    json.dumps(json_data).encode(),
                ),
                timeout=timeout,
            )
        except Exception as e:
            logger.warning("Memory [note candidate search] failed: %s", e)
            return empty

        if result is None:
            return empty

        data = json.loads(result.decode())

        if data.get("error"):
            logger.warning("Memory [note candidate search] err: %s", data["error"])
            return empty

        results = data.get("results") or []

        # Never let a short response shift candidates onto the wrong record.
        if len(results) != len(texts):
            logger.warning(
                "Memory [note candidate search] count mismatch: got %d want %d",
                len(results),
                len(texts),
            )
            return empty

        return results
