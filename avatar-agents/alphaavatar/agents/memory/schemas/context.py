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

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from alphaavatar.agents.utils.time import application_now


def _normalize_id(value: str) -> str:
    value = str(value).strip()
    if not value:
        raise ValueError("id cannot be empty")
    return value


class MemoryContextRef(BaseModel):
    episode_id: str
    context_id: str
    session_id: str | None = None

    parent_context_id: str | None = None
    task_id: str | None = None

    created_at: datetime = Field(default_factory=application_now)

    @field_validator("episode_id", "context_id")
    @classmethod
    def _validate_required_id(cls, value: str) -> str:
        return _normalize_id(value)

    @field_validator("parent_context_id", "session_id", "task_id")
    @classmethod
    def _validate_optional_id(cls, value: str | None) -> str | None:
        return _normalize_id(value) if value is not None else None

    @model_validator(mode="after")
    def _validate_parent(self) -> MemoryContextRef:
        if self.parent_context_id == self.context_id:
            raise ValueError("context cannot be its own parent")
        return self

    def child(
        self,
        *,
        context_id: str,
        episode_id: str | None = None,
        session_id: str | None = None,
        task_id: str | None = None,
    ) -> MemoryContextRef:
        return MemoryContextRef(
            episode_id=episode_id or self.episode_id,
            context_id=context_id,
            parent_context_id=self.context_id,
            session_id=session_id if session_id is not None else self.session_id,
            task_id=task_id,
        )
