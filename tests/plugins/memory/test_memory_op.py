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
from alphaavatar.agents.memory import MemoryItem, MemoryNote, MemoryType
from alphaavatar.plugins.memory.memory_op import (
    NOTE_PAYLOAD_KEY,
    flatten_records,
    rebuild_from_items,
)

TS = "Timezone: Asia/Shanghai; Timezone Source: test; Time: Sunday, August 9, 2026, 10:00 AM"


def _item() -> MemoryItem:
    return MemoryItem(
        memory_id="i1",
        session_id="s1",
        object_ids=["u1"],
        value="user likes espresso",
        topic="coffee",
        timestamp=TS,
        memory_type=MemoryType.CONVERSATION,
    )


def _note() -> MemoryNote:
    return MemoryNote(
        memory_id="n1",
        session_id="s1",
        object_ids=["u1"],
        topic="trip",
        timestamp=TS,
        memory_type=MemoryType.CONVERSATION,
        summary="Kyoto trip planned.",
        facts=["Travelling in November."],
        keywords=["kyoto"],
    )


def test_embedding_text_is_separate_from_page_content():
    row = flatten_records([_item()], include_topic=True)[0]
    assert row["page_content"] == "user likes espresso"
    assert row["embedding_text"] == "coffee\nuser likes espresso"


def test_note_row_keeps_memory_item_doc_kind():
    """Writing doc_kind='memory_note' would hide notes from _search_rows."""
    assert flatten_records([_note()])[0]["doc_kind"] == "memory_item"


def test_note_roundtrip_preserves_sfk():
    rebuilt = rebuild_from_items(flatten_records([_note()]))[0]
    assert isinstance(rebuilt, MemoryNote)
    assert rebuilt.summary == "Kyoto trip planned."
    assert rebuilt.facts == ["Travelling in November."]
    assert rebuilt.keywords == ["kyoto"]
    assert NOTE_PAYLOAD_KEY not in rebuilt.extra_data
    assert rebuilt.value == "Kyoto trip planned.\nTravelling in November."


def test_legacy_row_rebuilds_as_plain_item():
    """Rows written before this change carry no note payload."""
    legacy = {
        "id": "old1",
        "page_content": "legacy memory",
        "metadata": {
            "session_id": "s0",
            "object_ids": [],
            "topic": "",
            "ts": TS,
            "memory_type": "User Interaction with Assistant",
            "graph_nodes": [],
            "graph_links": [],
            "extra_data": {},
        },
    }
    rebuilt = rebuild_from_items([legacy])[0]
    assert type(rebuilt) is MemoryItem
    assert rebuilt.value == "legacy memory"
