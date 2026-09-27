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
from pydantic import BaseModel, Field, model_validator

from ..enums import MemoryOutboxTarget


class MemoryCheckpointAdvance(BaseModel):
    from_sequence: int = Field(default=0, ge=0)
    to_sequence: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_sequence(self) -> "MemoryCheckpointAdvance":
        if self.to_sequence < self.from_sequence:
            raise ValueError("to_sequence must be >= from_sequence")
        return self


class MemoryCommitResult(BaseModel):
    committed: bool
    duplicate: bool
    memory_ids: list[str]
    checkpoint_sequence: int | None = None


class MemoryOutboxEvent(BaseModel):
    event_id: int
    target: MemoryOutboxTarget
    memory_id: str
    revision: int
    attempts: int

    available_at: float
    lease_owner: str | None = None
    lease_until: float | None = None
    last_error: str | None = None
