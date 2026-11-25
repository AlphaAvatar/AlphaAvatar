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

from typing import Any


class EmbeddingProbeError(RuntimeError):
    """The embedding provider failed the start probe; the provider's error is its cause."""


def probe_dimension(embeddings: Any) -> int:
    """The embedding dimension, from one probe request to the provider."""
    try:
        return len(embeddings.embed_query("dimension-probe"))
    except Exception as error:
        raise EmbeddingProbeError("The embedding provider failed the start probe") from error
