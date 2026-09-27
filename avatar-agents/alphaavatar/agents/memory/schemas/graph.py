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
import uuid
from typing import Any

from pydantic import BaseModel, Field


class GraphNodeMention(BaseModel):
    """
    Lightweight graph anchor produced by the memory extractor.

    This is NOT a stored graph node yet.
    Runtime / GraphBuilder will normalize it into MemoryGraphNode.
    """

    key: str | None = Field(
        default=None,
        description="Stable key if known, such as face:face_1, voice:voice_2, text:world_cup.",
    )
    type: str | None = Field(
        default=None,
        description="Optional node type hint, such as text, image, audio, face, voice, object, tool.",
    )
    content: str = Field(
        default="",
        description="Searchable node content or description.",
    )
    weight: float = Field(default=1.0)


class MemoryGraphNode(BaseModel):
    """
    Stored graph node.

    id is storage-unique.
    key is used for dedupe / entity resolution / cross-session association.
    content is used for retrieval.
    """

    id: str = Field(default_factory=lambda: f"node_{uuid.uuid4().hex}")
    key: str
    type: str
    content: str

    embedding: list[float] | None = None
    weight: float = 1.0
    extra_data: dict[str, Any] = Field(default_factory=dict)


class MemoryGraphLink(BaseModel):
    source_id: str | None = None
    target_id: str | None = None

    source_key: str
    target_key: str

    weight: float = 1.0
    extra_data: dict[str, Any] = Field(default_factory=dict)
