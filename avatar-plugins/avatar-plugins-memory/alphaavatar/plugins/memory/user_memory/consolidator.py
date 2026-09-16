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

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime
from typing import Any

from alphaavatar.agents.memory.enums import MemoryKind
from alphaavatar.agents.memory.schemas import (
    MemoryItem,
    MemorySearchHit,
)

from ..log import logger
from .candidates import (
    RecalledCandidateCache,
    consolidated_from_hits,
    merge_candidates,
)
from .config import CandidateSource, ConsolidationMode, MemoryPipelineConfig
from .consolidation_op import apply_assignments
from .prompts import render_candidates, render_incoming
from .schema import ConsolidationPlan, ConsolidationResult

CandidateSearch = Callable[
    ...,
    Awaitable[list[list[MemorySearchHit]]],
]
PlanConsolidation = Callable[..., Awaitable[ConsolidationPlan]]


def _owner_keys(item: MemoryItem) -> tuple[str, ...]:
    return tuple(sorted(ref.key for ref in item.owner_refs))


def _validate_batch(items: list[MemoryItem]) -> MemoryItem:
    if not items:
        raise ValueError("Consolidation batch cannot be empty")

    first = items[0]
    if first.kind is not MemoryKind.ATOMIC:
        raise ValueError("Consolidation batch must contain atomic memories")

    owners = _owner_keys(first)

    for item in items[1:]:
        if item.kind is not MemoryKind.ATOMIC:
            raise ValueError("Consolidation batch must contain atomic memories")
        if item.memory_type != first.memory_type:
            raise ValueError("Cannot consolidate different memory types")
        if item.scope.key != first.scope.key:
            raise ValueError("Cannot consolidate memories across scopes")
        if _owner_keys(item) != owners:
            raise ValueError("Cannot consolidate memories across owner domains")

    return first


def _compatible_candidates(
    items: list[MemoryItem],
    candidates: Iterable[MemoryItem],
) -> list[MemoryItem]:
    first = _validate_batch(items)
    owners = _owner_keys(first)

    return [
        candidate
        for candidate in candidates
        if candidate.kind is MemoryKind.CONSOLIDATED
        and candidate.memory_type == first.memory_type
        and candidate.scope.key == first.scope.key
        and _owner_keys(candidate) == owners
    ]


def _log_hit_scores(
    items: list[MemoryItem],
    hits: list[list[MemorySearchHit]],
    *,
    threshold: float,
) -> None:
    if not logger.isEnabledFor(logging.DEBUG):
        return

    for item, item_hits in zip(items, hits, strict=False):
        if not item_hits:
            logger.debug(
                "[Memory] consolidation candidates memory=%s none",
                item.memory_id[:8],
            )
            continue

        ranked = sorted(
            (
                hit.score,
                hit.memory.memory_id[:8],
            )
            for hit in item_hits
        )

        logger.debug(
            "[Memory] consolidation candidates memory=%s threshold=%.2f -> %s",
            item.memory_id[:8],
            threshold,
            ", ".join(f"{memory_id}:{score:.4f}" for score, memory_id in reversed(ranked)),
        )


class MemoryConsolidator:
    def __init__(
        self,
        config: MemoryPipelineConfig,
        *,
        candidate_search: CandidateSearch,
        plan: PlanConsolidation,
    ) -> None:
        self._config = config
        self._candidate_search = candidate_search
        self._plan = plan
        self._recalled_candidates = RecalledCandidateCache()

    @property
    def enabled(self) -> bool:
        return self._config.consolidation.enabled

    @property
    def resolve_sources(self) -> bool:
        return self._config.consolidation.mode is ConsolidationMode.SESSION_MERGE

    def record_recall(self, records: Iterable[MemoryItem]) -> None:
        self._recalled_candidates.record(records)

    async def consolidate_session(
        self,
        items: list[MemoryItem],
        *,
        session_content: str,
        updated_at: datetime,
        trace_metadata: dict[str, Any],
    ) -> list[MemoryItem]:
        return (
            await self._consolidate_session(
                items,
                session_content=session_content,
                updated_at=updated_at,
                trace_metadata=trace_metadata,
            )
        ).all_writes()

    async def _consolidate_session(
        self,
        items: list[MemoryItem],
        *,
        session_content: str,
        updated_at: datetime,
        trace_metadata: dict[str, Any],
    ) -> ConsolidationResult:
        if not items:
            return ConsolidationResult(
                source_items=[],
                to_insert=[],
                to_rewrite=[],
            )

        first = _validate_batch(items)
        fallback = ConsolidationResult(
            source_items=list(items),
            to_insert=[],
            to_rewrite=[],
        )

        if not self.enabled:
            return fallback

        try:
            candidates = await self._collect_candidates(items)

            plan = await self._invoke(
                items,
                candidates=candidates,
                session_content=session_content,
                trace_metadata=trace_metadata,
            )

            result = apply_assignments(
                items,
                candidates,
                plan,
                resolve_sources=self.resolve_sources,
                updated_at=updated_at,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "[Memory] consolidation failed context=%s; persisting atomic memories",
                first.context.context_id,
            )
            return fallback

        logger.info(
            "[Memory] consolidation context=%s items=%d candidates=%d inserted=%d rewritten=%d",
            first.context.context_id,
            len(items),
            len(candidates),
            len(result.to_insert),
            len(result.to_rewrite),
        )

        return result

    async def _collect_candidates(
        self,
        items: list[MemoryItem],
    ) -> list[MemoryItem]:
        first = _validate_batch(items)

        if self._config.consolidation.mode is ConsolidationMode.SESSION_SUMMARY:
            return []

        maintenance = self._config.maintenance
        source = maintenance.candidate_source
        from_recall: list[MemoryItem] = []

        if source in (
            CandidateSource.QUERY_RECALL,
            CandidateSource.UNION,
        ):
            from_recall = self._recalled_candidates.candidates()

        from_lookup: list[MemoryItem] = []

        if source in (
            CandidateSource.CONSOLIDATED_LOOKUP,
            CandidateSource.UNION,
        ):
            hits = await self._candidate_search(
                [item.embedding_text() for item in items],
                owner_refs=first.owner_refs,
                context=first.context,
            )

            _log_hit_scores(
                items,
                hits,
                threshold=maintenance.similarity_threshold,
            )

            from_lookup = consolidated_from_hits(
                hits,
                threshold=maintenance.similarity_threshold,
                limit=maintenance.max_candidates_per_item,
            )

        return _compatible_candidates(
            items,
            merge_candidates(
                from_lookup,
                from_recall,
            ),
        )

    async def _invoke(
        self,
        items: list[MemoryItem],
        *,
        candidates: list[MemoryItem],
        session_content: str,
        trace_metadata: dict[str, Any],
    ) -> ConsolidationPlan:
        session_summary = self._config.consolidation.mode is ConsolidationMode.SESSION_SUMMARY

        payload: dict[str, Any] = {
            "session_content": session_content,
            "incoming": render_incoming(items),
        }

        if not session_summary:
            payload["candidates"] = render_candidates(candidates)

        return await self._plan(
            payload=payload,
            session_summary=session_summary,
            metadata={
                **trace_metadata,
                "operation": "memory_consolidation",
            },
            timeout=self._config.maintenance.timeout,
        )
