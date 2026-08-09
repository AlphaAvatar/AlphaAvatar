from alphaavatar.agents.memory import MemoryItem, MemoryType


def _item(**kw) -> MemoryItem:
    base = {
        "session_id": "s1",
        "value": "user likes espresso",
        "timestamp": "Timezone: Asia/Shanghai; Timezone Source: test; Time: Sunday, August 9, 2026, 10:00 AM",
        "memory_type": MemoryType.CONVERSATION,
    }
    base.update(kw)
    return MemoryItem(**base)


def test_render_line_with_topic():
    assert _item(topic="coffee preference").render_line() == (
        "Timestamp: Timezone: Asia/Shanghai; Timezone Source: test; Time: Sunday, August 9, 2026, 10:00 AM; Topic: coffee preference; Content: user likes espresso"
    )


def test_render_line_without_topic():
    assert _item().render_line() == (
        "Timestamp: Timezone: Asia/Shanghai; Timezone Source: test; Time: Sunday, August 9, 2026, 10:00 AM; Content: user likes espresso"
    )


def test_embedding_text_can_include_topic():
    assert _item(topic="coffee preference").embedding_text(include_topic=True) == (
        "coffee preference\nuser likes espresso"
    )


def test_render_line_strips_trailing_whitespace():
    assert _item(value="user likes espresso   ").render_line() == (
        "Timestamp: Timezone: Asia/Shanghai; Timezone Source: test; Time: Sunday, August 9, 2026, 10:00 AM; Content: user likes espresso"
    )
