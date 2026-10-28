# Copyright 2025 AlphaAvatar project
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

from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from alphaavatar.core.workspace import path_key
from alphaavatar.core.workspace.paths import absolute_root


class AvatarInfoConfig(BaseModel):
    """Avatar configuration; resolving and preparing paths belongs to the application."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=256)
    name: str = Field(default="Assistant", min_length=1)
    introduction: str = "You are a helpful voice AI assistant."
    timezone: str | None = None
    workspace_root: str | None = Field(
        default=None, description="Explicit complete Avatar workspace root, without ID appending."
    )

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_workspace(cls, value: Any) -> Any:
        if isinstance(value, dict) and "work_dir" in value:
            raise ValueError(
                "avatar.work_dir used a base directory with the Avatar ID appended. "
                "Replace it with avatar.workspace_root pointing to the existing complete "
                "workspace directory; back up existing data before changing its location."
            )
        return value

    @field_validator("id")
    @classmethod
    def check_id(cls, value: str) -> str:
        path_key(value)
        return value

    @field_validator("workspace_root")
    @classmethod
    def check_workspace_root(cls, value: str | None) -> str | None:
        return str(absolute_root(Path(value))) if value is not None else None

    @field_validator("timezone")
    @classmethod
    def check_timezone(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ZoneInfo(value)
            except (ValueError, ZoneInfoNotFoundError):
                raise ValueError("avatar.timezone must be an IANA timezone name") from None
        return value
