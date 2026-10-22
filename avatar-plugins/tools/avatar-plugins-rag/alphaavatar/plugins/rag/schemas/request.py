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
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..enums import RAGOp


class RAGRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    op: RAGOp
    data_source: str = Field(default="all", min_length=1)
    query: str | None = Field(default=None, min_length=1)
    file_paths_or_dir: list[str] | None = Field(default=None, min_length=1)
    monologue: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_operation(self) -> RAGRequest:
        if self.op == RAGOp.QUERY and not self.query:
            raise ValueError("RAG query requires a nonempty query")
        if self.op == RAGOp.INDEXING and (
            not self.file_paths_or_dir or any(not path.strip() for path in self.file_paths_or_dir)
        ):
            raise ValueError("RAG indexing requires nonempty paths")
        return self
