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

import json
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ModelProviderItem:
    """Opaque continuation, never user-visible text or executable control instructions.

    The producing backend validates scope on replay. payload_json is immutable and
    deliberately excluded from repr; generic diagnostics must keep it redacted.
    """

    id: str
    backend: str
    scope: str
    payload_json: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.id or not self.backend or not self.scope:
            raise ValueError("Provider continuation identity cannot be empty")
        payload = json.loads(self.payload_json)
        if not isinstance(payload, dict) or payload.get("id") != self.id:
            raise ValueError("Provider continuation must contain its original item identity")

    def diagnostic(self) -> dict[str, str | bool]:
        return {"id": self.id, "backend": self.backend, "redacted": True}
