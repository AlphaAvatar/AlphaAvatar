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
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from alphaavatar.agents.memory import MemoryItem, MemoryNote

from .base import MaintenanceResult


class JudgeDecision(str, Enum):
    ADD = "add"
    NOOP = "noop"
    UPDATE = "update"


class JudgeVerdict(BaseModel):
    index: int = Field(description="Index of the incoming memory this verdict is for.")
    decision: JudgeDecision
    target_ids: list[str] = Field(default_factory=list)


class JudgeVerdicts(BaseModel):
    verdicts: list[JudgeVerdict] = Field(default_factory=list)


class RewrittenMemory(BaseModel):
    id: str
    summary: str = ""
    keywords: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)


class RewrittenMemories(BaseModel):
    updates: list[RewrittenMemory] = Field(default_factory=list)


def apply_verdicts(
    *,
    incoming: list[MemoryItem],
    verdicts: list[JudgeVerdict],
    candidates_by_index: dict[int, list[MemoryItem]],
    rewritten_by_id: dict[str, MemoryItem],
) -> MaintenanceResult:
    """Turn judge verdicts plus rewritten content into a MaintenanceResult.

    Pure function: no LLM, no VDB. The correctness rules live here.
    """
    result = MaintenanceResult()
    verdict_by_index = {v.index: v for v in verdicts}

    for index, record in enumerate(incoming):
        verdict = verdict_by_index.get(index)

        if verdict is None or verdict.decision == JudgeDecision.ADD:
            result.to_insert.append(record)
            continue

        if verdict.decision == JudgeDecision.NOOP:
            result.dropped.append(record)
            continue

        # UPDATE
        candidate_ids = {c.memory_id for c in candidates_by_index.get(index, [])}
        rewritten = [
            rewritten_by_id[tid]
            for tid in verdict.target_ids
            if tid in candidate_ids and tid in rewritten_by_id
        ]

        if not rewritten:
            # The rewrite step produced nothing usable. Falling back to add is
            # the safe choice: dropping here would lose the memory entirely.
            result.to_insert.append(record)
            continue

        result.to_rewrite.extend(rewritten)
        result.dropped.append(record)

    return result


class LLMJudgeStrategy:
    """ops contains noop and/or update.

    Records with no sufficiently similar existing memory skip the LLM entirely,
    so cost scales with the actual duplication rate rather than with volume.
    """

    def __init__(
        self,
        *,
        candidate_search,
        judge,
        rewriter,
        threshold: float,
        max_candidates: int,
        allow_update: bool,
    ) -> None:
        self._candidate_search = candidate_search
        self._judge = judge
        self._rewriter = rewriter
        self._threshold = threshold
        self._max_candidates = max_candidates
        self._allow_update = allow_update

    @staticmethod
    def filter_hits(
        hits: list[dict[str, Any]],
        *,
        threshold: float,
        limit: int,
    ) -> list[dict[str, Any]]:
        kept = [hit for hit in hits if float(hit.get("score", 0.0)) >= threshold]
        return kept[:limit]

    async def apply(
        self,
        records: list[MemoryItem],
        *,
        trace_metadata: dict[str, Any],
    ) -> MaintenanceResult:
        if not records:
            return MaintenanceResult()

        all_hits = await self._candidate_search([r.embedding_text() for r in records])

        candidates_by_index: dict[int, list[MemoryItem]] = {}
        for index, hits in enumerate(all_hits):
            kept = self.filter_hits(
                hits,
                threshold=self._threshold,
                limit=self._max_candidates,
            )
            # Only notes may be updated; legacy plain items can trigger noop at
            # most. This avoids an item -> note shape conversion.
            candidates_by_index[index] = [
                c for c in _rebuild_candidates(kept) if isinstance(c, MemoryNote)
            ]

        if not any(candidates_by_index.values()):
            return MaintenanceResult(to_insert=list(records))

        verdicts = await self._judge(
            incoming=records,
            candidates_by_index=candidates_by_index,
            allow_update=self._allow_update,
            trace_metadata=trace_metadata,
        )

        rewritten_by_id: dict[str, MemoryItem] = {}
        if self._allow_update:
            rewritten_by_id = await self._rewriter(
                incoming=records,
                verdicts=verdicts,
                candidates_by_index=candidates_by_index,
                trace_metadata=trace_metadata,
            )

        return apply_verdicts(
            incoming=records,
            verdicts=verdicts,
            candidates_by_index=candidates_by_index,
            rewritten_by_id=rewritten_by_id,
        )


def _rebuild_candidates(hits: list[dict[str, Any]]) -> list[MemoryItem]:
    from ..memory_op import rebuild_from_items

    return rebuild_from_items([hit["item"] for hit in hits])
