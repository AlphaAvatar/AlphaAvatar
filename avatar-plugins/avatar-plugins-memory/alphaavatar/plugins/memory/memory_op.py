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
from typing import Any

from pydantic import BaseModel, Field

from alphaavatar.agents.memory import MemoryItem


class PatchOp(BaseModel):
    value: str = Field(
        default="",
        description="The concise new memory text.",
    )
    entities: list[str] = Field(
        default_factory=list,
        description="Related entities extracted from the memory value are used to associate with other memory items.",
    )
    topic: str | None = Field(
        default=None, description="The topic described by the current memory content"
    )


class MemoryDelta(BaseModel):
    user_or_tool_memory_entries: list[PatchOp] = Field(
        default_factory=list,
        description="A list of memory contents where the Assistant interacts with the user based on the conversation content.",
    )
    assistant_memory_entries: list[PatchOp] = Field(
        default_factory=list,
        description="The Assistant's own memory list is generated based on the conversation content and the memory content list of the Assistant's interaction with the user.",
    )


def norm_token(s: Any) -> str:
    """Normalize for case/whitespace-insensitive equality."""
    return " ".join(str(s).strip().lower().split())


def flatten_items(memory_items: list[MemoryItem]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for memory in memory_items:
        items.append(
            {
                "id": memory.memory_id,
                "page_content": memory.value,
                "metadata": {
                    "session_id": memory.session_id,
                    "object_id": memory.object_id,
                    "entities": memory.entities,
                    "topic": memory.topic,
                    "ts": memory.timestamp,
                    "memory_type": memory.memory_type,
                },
            }
        )

    return items


def rebuild_from_items(items: list[dict[str, Any]]) -> list[MemoryItem]:
    out: list[MemoryItem] = []

    for it in items:
        mid = it.get("id", None)
        value = it.get("page_content", None)
        meta = it.get("metadata", {})

        if mid is None or value is None:
            continue

        out.append(
            MemoryItem(
                memory_id=mid,
                value=value,
                session_id=meta.get("session_id"),
                object_id=meta.get("object_id"),
                entities=meta.get("entities"),
                topic=meta.get("topic"),
                timestamp=meta.get("ts"),
                memory_type=meta.get("memory_type"),
            )
        )

    return out
