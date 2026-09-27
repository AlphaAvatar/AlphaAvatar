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
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class RetrievalOp(StrEnum):
    TEXT_SEARCH = "text_search"
    GRAPH_SEARCH = "graph_search"


class RetrievalCapabilityInput(BaseModel):
    op: RetrievalOp

    query: str | None = None

    node_key: str | None = None
    node_query: str | None = None
    node_type: str | None = None

    max_hops: int = Field(default=0, ge=0, le=4)
    top_k: int = Field(default=10, ge=1, le=50)

    @model_validator(mode="after")
    def _validate_op(self) -> "RetrievalCapabilityInput":
        if self.op is RetrievalOp.TEXT_SEARCH:
            if not str(self.query or "").strip():
                raise ValueError("query is required for text_search")

        elif self.op is RetrievalOp.GRAPH_SEARCH:
            if not str(self.node_key or "").strip() and not str(self.node_query or "").strip():
                raise ValueError("node_key or node_query is required for graph_search")

        return self
