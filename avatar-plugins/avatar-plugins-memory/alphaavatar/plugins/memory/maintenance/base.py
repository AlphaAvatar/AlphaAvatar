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
from dataclasses import dataclass, field
from typing import Any, Protocol

from alphaavatar.agents.memory import MemoryItem


@dataclass
class MaintenanceResult:
    """Outcome of the indexing/maintenance stage.

    to_insert  -- newly created records
    to_rewrite -- existing records whose content was merged/updated. These KEEP
                  their original memory_id so the VDB save (delete-by-id +
                  reinsert) behaves as an upsert.
    dropped    -- records discarded as redundant (the Noop operation)
    """

    to_insert: list[MemoryItem] = field(default_factory=list)
    to_rewrite: list[MemoryItem] = field(default_factory=list)
    dropped: list[MemoryItem] = field(default_factory=list)

    def all_writes(self) -> list[MemoryItem]:
        return [*self.to_insert, *self.to_rewrite]


class MaintenanceStrategy(Protocol):
    async def apply(
        self,
        records: list[MemoryItem],
        *,
        trace_metadata: dict[str, Any],
    ) -> MaintenanceResult: ...


class AddOnlyStrategy:
    """ops == [add]. Every extracted record is inserted verbatim."""

    async def apply(
        self,
        records: list[MemoryItem],
        *,
        trace_metadata: dict[str, Any],
    ) -> MaintenanceResult:
        return MaintenanceResult(to_insert=list(records))
