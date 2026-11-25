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
"""The RAG capability's request: what the model is offered, and what it is refused."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from alphaavatar.plugins.rag.schemas import RAGRequest


def test_the_model_is_offered_no_monologue_and_one_sent_is_refused() -> None:
    # Tools take no monologue; Loop and Status own what is said while a tool runs.
    assert "monologue" not in RAGRequest.model_json_schema()["properties"]
    assert RAGRequest(op="query", query="words").query == "words"
    with pytest.raises(ValidationError, match="monologue"):
        RAGRequest(op="query", query="words", monologue="Looking it up")
