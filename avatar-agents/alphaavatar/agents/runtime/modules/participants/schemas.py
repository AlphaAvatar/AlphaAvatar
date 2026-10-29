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

from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphaavatar.core.session.schemas.validation import validate_identity


class ParticipantInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: str | None = Field(
        description="User identity supported by the evidence, or null to clear a mistaken match"
    )
    reason: str = Field(
        min_length=1, max_length=2048, description="Evidence for this identity decision"
    )
    participant_id: str | None = Field(
        default=None,
        description="A current Turn participant; omit only when exactly one is present",
    )
    basis_sequence: int | None = Field(
        default=None,
        ge=0,
        strict=True,
        description="Version from a previous identity result; defaults to the Turn actor's version",
    )

    @field_validator("user_id", "participant_id")
    @classmethod
    def _validate_identity(cls, value: str | None) -> str | None:
        return None if value is None else validate_identity(value)

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must describe the evidence for this decision")
        return value
