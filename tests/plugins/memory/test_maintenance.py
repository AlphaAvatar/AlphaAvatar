from alphaavatar.agents.memory import MemoryNote, MemoryType
from alphaavatar.plugins.memory.maintenance import (
    JudgeDecision,
    JudgeVerdict,
    LLMJudgeStrategy,
    apply_verdicts,
)

TS = "Timezone: Asia/Shanghai; Timezone Source: test; Time: Sunday, August 9, 2026, 10:00 AM"


def _note(mid: str = "n1", summary: str = "s") -> MemoryNote:
    return MemoryNote(
        memory_id=mid,
        session_id="s1",
        object_ids=["u1"],
        timestamp=TS,
        memory_type=MemoryType.CONVERSATION,
        summary=summary,
        facts=["f1"],
        keywords=["k1"],
    )


def test_noop_drops_the_incoming_record():
    result = apply_verdicts(
        incoming=[_note("new1")],
        verdicts=[JudgeVerdict(index=0, decision=JudgeDecision.NOOP)],
        candidates_by_index={0: [_note("old1")]},
        rewritten_by_id={},
    )
    assert result.to_insert == []
    assert [r.memory_id for r in result.dropped] == ["new1"]


def test_update_writes_the_target_under_its_original_id():
    """Keeping the id is what makes the VDB delete+reinsert behave as an upsert."""
    result = apply_verdicts(
        incoming=[_note("new1", summary="new info")],
        verdicts=[JudgeVerdict(index=0, decision=JudgeDecision.UPDATE, target_ids=["old1"])],
        candidates_by_index={0: [_note("old1", summary="old info")]},
        rewritten_by_id={"old1": _note("old1", summary="merged info")},
    )
    assert result.to_insert == []
    assert [r.memory_id for r in result.to_rewrite] == ["old1"]
    assert result.to_rewrite[0].summary == "merged info"
    assert [r.memory_id for r in result.dropped] == ["new1"]


def test_update_without_a_rewrite_falls_back_to_add():
    """Dropping here would lose the memory entirely, so add is the safe fallback."""
    result = apply_verdicts(
        incoming=[_note("new1")],
        verdicts=[JudgeVerdict(index=0, decision=JudgeDecision.UPDATE, target_ids=["old1"])],
        candidates_by_index={0: [_note("old1")]},
        rewritten_by_id={},
    )
    assert [r.memory_id for r in result.to_insert] == ["new1"]
    assert result.to_rewrite == []


def test_update_targeting_an_unlisted_id_falls_back_to_add():
    """A hallucinated id must not cause a write to an arbitrary memory."""
    result = apply_verdicts(
        incoming=[_note("new1")],
        verdicts=[JudgeVerdict(index=0, decision=JudgeDecision.UPDATE, target_ids=["ghost"])],
        candidates_by_index={0: [_note("old1")]},
        rewritten_by_id={"ghost": _note("ghost")},
    )
    assert [r.memory_id for r in result.to_insert] == ["new1"]
    assert result.to_rewrite == []


def test_missing_verdict_defaults_to_add():
    """An empty judge response (the provider fallback) must not lose memories."""
    result = apply_verdicts(
        incoming=[_note("new1"), _note("new2")],
        verdicts=[],
        candidates_by_index={0: [_note("old1")], 1: []},
        rewritten_by_id={},
    )
    assert [r.memory_id for r in result.to_insert] == ["new1", "new2"]


def test_filter_hits_applies_threshold_then_limit():
    hits = [
        {"item": {"id": "a"}, "score": 0.95},
        {"item": {"id": "b"}, "score": 0.85},
        {"item": {"id": "c"}, "score": 0.50},
    ]
    kept = LLMJudgeStrategy.filter_hits(hits, threshold=0.82, limit=5)
    assert [h["item"]["id"] for h in kept] == ["a", "b"]
    assert len(LLMJudgeStrategy.filter_hits(hits, threshold=0.0, limit=2)) == 2


async def test_no_candidates_skips_the_llm_entirely():
    calls = []

    async def never(**kw):
        calls.append(kw)
        raise AssertionError("LLM must not be called when nothing collides")

    strategy = LLMJudgeStrategy(
        candidate_search=lambda texts: _resolved([[] for _ in texts]),
        judge=never,
        rewriter=never,
        threshold=0.82,
        max_candidates=5,
        allow_update=True,
    )

    result = await strategy.apply([_note("new1")], trace_metadata={})
    assert [r.memory_id for r in result.to_insert] == ["new1"]
    assert calls == []


def _resolved(value):
    async def _inner():
        return value

    return _inner()
