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
"""A vector store's start probe: its provider's failure says so by its type."""

from __future__ import annotations

import pytest

from alphaavatar.agents.utils.vdb.probe import EmbeddingProbeError, probe_dimension


class Embeddings:
    def __init__(self, error: Exception | None = None) -> None:
        self.error, self.calls = error, []

    def embed_query(self, text: str) -> list[float]:
        self.calls.append(text)
        if self.error is not None:
            raise self.error
        return [0.0] * 8


def test_the_probe_is_one_request_and_its_failure_is_the_providers() -> None:
    embeddings = Embeddings()
    assert probe_dimension(embeddings) == 8 and embeddings.calls == ["dimension-probe"]
    refused = PermissionError("401 from the provider")
    with pytest.raises(EmbeddingProbeError) as raised:
        probe_dimension(Embeddings(refused))
    # The provider's own error stays its cause, as a runner's diagnostic shows it.
    assert raised.value.__cause__ is refused
