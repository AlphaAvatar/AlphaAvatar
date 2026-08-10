from alphaavatar.agents.memory import MemoryType
from alphaavatar.agents.memory.schema.memory_item import MemoryItem
from alphaavatar.agents.memory.state import MemoryState

TS = "Timezone: Asia/Shanghai; Timezone Source: test; Time: Sunday, August 9, 2026, 10:00 AM"


def _item(value: str) -> MemoryItem:
    return MemoryItem(
        updated=True,
        session_id="s1",
        value=value,
        timestamp=TS,
        memory_type=MemoryType.CONVERSATION,
    )


def test_state_drops_records_beyond_the_cap():
    """MemoryState is a rendering view and truncates to maximum_memory_num.

    This is why every extraction path persists the list it produced rather than
    reading back from here: routing persistence through this structure drops the
    earliest records of any memory type that extracted more than the cap in one
    session. The call sites are what enforce that; this test pins the hazard so
    it stays visible if one of them is ever pointed back at the view.
    """
    state = MemoryState(maximum_memory_num=3)
    state.add(MemoryType.CONVERSATION, [_item(f"m{i}") for i in range(10)])

    kept = state.get(memory_type=MemoryType.CONVERSATION)
    assert len(kept) == 3
    assert [item.value for item in kept] == ["m7", "m8", "m9"]


def test_mark_saved_clears_the_flag_so_a_retry_does_not_rewrite():
    state = MemoryState(maximum_memory_num=10)
    items = [_item("a"), _item("b")]
    state.add(MemoryType.CONVERSATION, items)

    state.mark_saved({items[0].memory_id})

    assert state.get(memory_type=MemoryType.CONVERSATION, updated=True) == [items[1]]
