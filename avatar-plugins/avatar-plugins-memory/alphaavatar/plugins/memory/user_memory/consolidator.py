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
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime
from typing import Any

from alphaavatar.agents.memory import MemoryCache, MemoryItem, MemoryNote
from alphaavatar.agents.utils.time import application_now

from ..log import logger
from .candidates import RecallLedger, merge_candidates, notes_from_hits
from .config import CandidateSource, MemoryPipelineConfig, NoteMode
from .note_op import apply_assignments
from .prompts import render_candidates, render_incoming
from .schema import ConsolidationResult, NoteConsolidation

# Note consolidation: candidate recall, one LLM call, deterministic mapping.

CandidateSearch = Callable[..., Awaitable[list[list[dict[str, Any]]]]]
Consolidate = Callable[..., Awaitable[NoteConsolidation]]


def _log_hit_scores(
    items: list[MemoryItem],
    hits: list[list[dict[str, Any]]],
    *,
    threshold: float,
) -> None:
    """Record what the nearest-neighbour search actually scored.

    Whether a note gets merged into hinges on these numbers, but they are
    otherwise invisible: only the surviving count reaches the result. Without
    them, "no candidates" cannot be told apart from "candidates just under the
    line", and the threshold cannot be calibrated on real data.
    """
    if not logger.isEnabledFor(logging.DEBUG):
        return

    for item, item_hits in zip(items, hits, strict=False):
        if not item_hits:
            logger.debug("[Memory] candidate scores item=%s: none returned", item.memory_id[:8])
            continue

        ranked = sorted(
            (float(h.get("score", 0.0)), str((h.get("item") or {}).get("id", ""))[:8])
            for h in item_hits
        )
        logger.debug(
            "[Memory] candidate scores item=%s threshold=%.2f -> %s",
            item.memory_id[:8],
            threshold,
            ", ".join(f"{note_id}:{score:.4f}" for score, note_id in reversed(ranked)),
        )


class NoteConsolidator:
    """Builds and maintains the note layer above a session's atomic memories."""

    def __init__(
        self,
        config: MemoryPipelineConfig,
        *,
        candidate_search: CandidateSearch,
        consolidate: Consolidate,
    ) -> None:
        self._config = config
        self._candidate_search = candidate_search
        self._consolidate = consolidate
        self._recall_ledger = RecallLedger()

    @property
    def enabled(self) -> bool:
        return self._config.note.enabled

    def record_recall(self, records: Iterable[MemoryItem]) -> None:
        """Tally what retrieval surfaced; recalled notes can become candidates."""
        self._recall_ledger.record(records)

    async def consolidate_session(
        self,
        items: list[MemoryItem],
        *,
        session_content: str,
        memory_cache: MemoryCache,
        updated_at: datetime,
        trace_metadata: dict[str, Any],
    ) -> list[MemoryItem]:
        """Return the records to persist for this session, notes included.

        Never raises and never drops an item: on any failure the items are
        returned untouched so the append-only layer still lands on disk.
        """
        return (
            await self._consolidate_session(
                items,
                session_content=session_content,
                memory_cache=memory_cache,
                updated_at=updated_at,
                trace_metadata=trace_metadata,
            )
        ).all_writes()

    async def _consolidate_session(
        self,
        items: list[MemoryItem],
        *,
        session_content: str,
        memory_cache: MemoryCache,
        updated_at: datetime,
        trace_metadata: dict[str, Any],
    ) -> ConsolidationResult:
        if not items:
            return ConsolidationResult()

        if not self.enabled:
            return ConsolidationResult(items=list(items))

        try:
            candidates = await self._collect_candidates(
                items,
                object_ids=memory_cache.object_ids,
            )
            consolidation = await self._invoke(
                items,
                candidates=candidates,
                session_content=session_content,
                trace_metadata=trace_metadata,
            )
        except Exception:
            logger.exception(
                "[Memory] note consolidation failed sid=%s; persisting items without notes",
                memory_cache.session_id,
            )
            return ConsolidationResult(items=list(items))

        result = apply_assignments(
            consolidation,
            items=items,
            candidates=candidates,
            session_id=memory_cache.session_id,
            object_ids=memory_cache.object_ids,
            created_at=application_now(),
            updated_at=updated_at,
            max_item_ids=self._config.note.max_item_ids,
        )

        logger.info(
            "[sid: %s] note consolidation items=%d candidates=%d inserted=%d rewritten=%d",
            memory_cache.session_id,
            len(items),
            len(candidates),
            len(result.to_insert),
            len(result.to_rewrite),
        )

        return result

    async def _collect_candidates(
        self,
        items: list[MemoryItem],
        *,
        object_ids: list[str],
    ) -> list[MemoryNote]:
        if self._config.note.mode is NoteMode.SESSION_SUMMARY:
            # A summary note never merges into an existing one, so recalling
            # candidates would only cost an RPC.
            return []

        maintenance = self._config.maintenance
        source = maintenance.candidate_source

        from_recall: list[MemoryNote] = []
        if source in (CandidateSource.QUERY_RECALL, CandidateSource.UNION):
            from_recall = self._recall_ledger.notes()

        from_lookup: list[MemoryNote] = []
        if source in (CandidateSource.NOTE_LOOKUP, CandidateSource.UNION):
            hits = await self._candidate_search(
                [item.embedding_text() for item in items],
                object_ids=object_ids,
            )
            _log_hit_scores(items, hits, threshold=maintenance.similarity_threshold)
            from_lookup = notes_from_hits(
                hits,
                threshold=maintenance.similarity_threshold,
                limit=maintenance.max_candidates_per_item,
            )

        return merge_candidates(from_lookup, from_recall)

    async def _invoke(
        self,
        items: list[MemoryItem],
        *,
        candidates: list[MemoryNote],
        session_content: str,
        trace_metadata: dict[str, Any],
    ) -> NoteConsolidation:
        session_summary = self._config.note.mode is NoteMode.SESSION_SUMMARY

        payload: dict[str, Any] = {
            "session_content": session_content,
            "incoming": render_incoming(items),
        }

        if not session_summary:
            payload["candidates"] = render_candidates(candidates)

        return await self._consolidate(
            payload=payload,
            session_summary=session_summary,
            metadata={**trace_metadata, "operation": "note_consolidation"},
            timeout=self._config.maintenance.timeout,
        )
