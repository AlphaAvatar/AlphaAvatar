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
"""A Qdrant recall narrows to what its readers read: each memory type through its kind of
owner, whatever the scope; readers who read nothing find nothing, never everything."""

from __future__ import annotations

from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

from alphaavatar.plugins.memory.storage.vdb.qdrant_runner import QdrantRunner


def test_a_recall_filter_is_each_memory_type_through_its_kind_of_owner() -> None:
    runner = QdrantRunner()
    readers = [
        {"memory_types": ["Assistant Memory"], "owner_keys": ["avatar:a"]},
        {"memory_types": ["Environment Observations"], "owner_keys": ["user:a"]},
    ]
    found = runner._build_filter(doc_kind="memory_item", visibility=readers)

    assert found == Filter(
        must=[
            FieldCondition(key="doc_kind", match=MatchValue(value="memory_item")),
            Filter(
                should=[
                    Filter(
                        must=[
                            FieldCondition(key="memory_type", match=MatchAny(any=types)),
                            FieldCondition(key="owner_keys", match=MatchAny(any=keys)),
                        ]
                    )
                    for types, keys in (
                        (["Assistant Memory"], ["avatar:a"]),
                        (["Environment Observations"], ["user:a"]),
                    )
                ]
            ),
        ]
    )
    # An empty should would match every point.
    nothing = runner._build_filter(doc_kind="memory_item", visibility=[])
    assert nothing.must[-1] == FieldCondition(key="doc_kind", match=MatchValue(value=""))
