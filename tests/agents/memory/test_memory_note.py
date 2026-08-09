from alphaavatar.agents.memory import MemoryNote, MemoryType
from alphaavatar.agents.memory.schema.memory_item import render_note_value


def _note(**kw) -> MemoryNote:
    base = {
        "session_id": "s1",
        "timestamp": "2026-08-09 10:00:00",
        "memory_type": MemoryType.CONVERSATION,
        "topic": "trip planning",
        "summary": "User planned a Kyoto trip for November.",
        "facts": ["User will travel to Kyoto in November.", "User prefers ryokan over hotels."],
        "keywords": ["kyoto", "november", "ryokan"],
    }
    base.update(kw)
    return MemoryNote(**base)


def test_render_note_value_joins_summary_and_facts():
    assert render_note_value("S", ["f1", "f2"]) == "S\nf1\nf2"


def test_render_note_value_skips_empty():
    assert render_note_value("", ["f1", ""]) == "f1"


def test_explicit_value_is_preserved():
    """Rebuilding from the VDB supplies value directly; it must not be overwritten."""
    note = _note(value="stored value")
    assert note.value == "stored value"


def test_render_line_is_single_line_and_labelled():
    assert _note().render_line() == (
        "Timestamp: 2026-08-09 10:00:00; "
        "Topic: trip planning; "
        "Summary: User planned a Kyoto trip for November.; "
        "Details: User will travel to Kyoto in November. | "
        "User prefers ryokan over hotels."
    )


def test_render_line_omits_details_when_no_facts():
    assert _note(facts=[]).render_line() == (
        "Timestamp: 2026-08-09 10:00:00; "
        "Topic: trip planning; "
        "Summary: User planned a Kyoto trip for November."
    )


def test_render_line_strips_trailing_whitespace():
    assert _note(summary="Kyoto trip.", facts=["Travelling in November.   "]).render_line() == (
        "Timestamp: 2026-08-09 10:00:00; "
        "Topic: trip planning; "
        "Summary: Kyoto trip.; "
        "Details: Travelling in November."
    )


def test_embedding_text_merges_s_f_k():
    assert _note().embedding_text() == (
        "User planned a Kyoto trip for November.\n"
        "User will travel to Kyoto in November.\n"
        "User prefers ryokan over hotels.\n"
        "kyoto november ryokan"
    )
