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

from dataclasses import dataclass

from .validation import identifier


@dataclass(frozen=True, slots=True)
class OutputSource:
    producer: str
    request_id: str | None = None
    item_id: str | None = None
    call_id: str | None = None

    def __post_init__(self) -> None:
        identifier(self.producer, "producer")
        for name in ("request_id", "item_id", "call_id"):
            identifier(getattr(self, name), name, optional=True)
        if (self.item_id is not None or self.call_id is not None) and self.request_id is None:
            raise ValueError("Model item/call provenance requires request_id")
