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
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from alphaavatar.agents.memory.schemas import GraphNodeMention


class PatchOp(BaseModel):
    value: str = Field(
        default="",
        description=(
            "Clean human-readable memory text. Do not include structured fields "
            "such as kind/topic/type/who/evidence/metadata."
        ),
    )
    topic: str | None = Field(
        default=None,
        description="Stable short topic label for retrieval and grouping.",
    )
    node_mentions: list[GraphNodeMention] = Field(
        default_factory=list,
        description=(
            "Lightweight graph anchors mentioned in this memory. "
            "Do not include embeddings, graph_nodes, graph_links, aliases, or evidence."
        ),
    )


class MemoryDelta(BaseModel):
    user_or_tool_memory_entries: list[PatchOp] = Field(default_factory=list)
    assistant_memory_entries: list[PatchOp] = Field(default_factory=list)


class EnvMemoryDelta(BaseModel):
    env_memory_entries: list[PatchOp] = Field(default_factory=list)


def norm_token(value: Any) -> str:
    return " ".join(str(value).strip().lower().split())


def norm_topic(value: str | None) -> str | None:
    if not value:
        return None
    return " ".join(value.strip().split()).lower()[:64]
