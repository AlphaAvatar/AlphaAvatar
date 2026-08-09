from alphaavatar.agents.memory import MemoryItem, MemoryType


def test_memory_item_constructs():
    item = MemoryItem(
        session_id="s1",
        value="hello",
        timestamp="2026-08-09 10:00:00",
        memory_type=MemoryType.CONVERSATION,
    )
    assert item.value == "hello"
    assert item.memory_id
