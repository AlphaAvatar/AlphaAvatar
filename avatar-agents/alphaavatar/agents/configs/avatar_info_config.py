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

import os
import pathlib
import uuid
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphaavatar.agents.utils.files.work_dirs import (
    WorkspacePaths,
    default_work_dir,
    prepare_workspace,
)


class AvatarInfoConfig(BaseModel):
    """Resolve an Avatar workspace once; child snapshots retain the absolute directory."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=1, max_length=256)
    name: str = Field(default="Assistant", min_length=1)
    introduction: str = "You are a helpful voice AI assistant."
    timezone: str | None = None
    work_dir: str = Field(
        default="", description="Workspace base directory; the Avatar ID is appended once."
    )

    @field_validator("id")
    @classmethod
    def check_id(cls, value: str) -> str:
        if (
            value in (".", "..")
            or value != value.strip()
            or any(char in value for char in "/\\\x00")
            or pathlib.PureWindowsPath(value).drive
        ):
            raise ValueError("Avatar ID must be a single nonempty directory name")
        return value

    def model_post_init(self, context) -> None:
        if isinstance(context, Mapping) and context.get("resolved_workspace") is True:
            if not pathlib.Path(self.work_dir).is_absolute():
                raise ValueError("A restored Avatar workspace must be absolute")
            os.environ["AVATAR_WORK_DIR"] = self.work_dir
            if self.timezone:
                os.environ["AVATAR_TIMEZONE"] = self.timezone
            return

        self.name = os.getenv("AVATAR_NAME") or self.name
        self.timezone = os.getenv("AVATAR_TIMEZONE") or self.timezone
        base = os.getenv("AVATAR_WORK_DIR") or self.work_dir
        root = (
            pathlib.Path(base).expanduser() / self.id if base.strip() else default_work_dir(self.id)
        )
        workspace = WorkspacePaths.from_root(root.resolve())
        prepare_workspace(workspace)

        self.work_dir = str(workspace.root)
        os.environ["AVATAR_WORK_DIR"] = self.work_dir
        if self.timezone:
            os.environ["AVATAR_TIMEZONE"] = self.timezone
