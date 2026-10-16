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
import os
import pathlib
import uuid
from collections.abc import Mapping

from pydantic import BaseModel, Field

from alphaavatar.agents.utils.files.work_dirs import (
    WorkspacePaths,
    default_work_dir,
    prepare_workspace,
)


class AvatarInfoConfig(BaseModel):
    """Avatar identity and workspace, with explicit restoration of a resolved configuration."""

    id: str = Field(
        default=uuid.uuid4().hex,
        description="Unique identifier for the avatar.",
    )
    name: str = Field(
        default="Assistant",
        description="Name of the avatar.",
    )
    introduction: str = Field(
        default="You are a helpful voice AI assistant.",
        description="Introduction of the avatar.",
    )
    timezone: str | None = Field(
        default=None,
        description="The time zone where the Avatar is deployed is used to align with the user's time zone for related task execution",
    )

    work_dir: str = Field(
        default="",
        description=(
            "Base work directory for this service. "
            "If empty, defaults to /var/lib/avatar_id (or ~/.local/share/avatar_id fallback). "
            "Will create subdirs: <work_dir>/.cache and <work_dir>/data."
        ),
    )

    def model_post_init(self, __context):
        if isinstance(__context, Mapping) and __context.get("resolved_workspace") is True:
            # Host IPC restores the validated identity and absolute workspace, not a new base path.
            # This context is supplied by the config loader, never by a user YAML field.
            if not pathlib.Path(self.work_dir).is_absolute():
                raise ValueError("A restored Avatar workspace must be absolute")
            os.environ["AVATAR_WORK_DIR"] = self.work_dir
            if self.timezone:
                os.environ["AVATAR_TIMEZONE"] = self.timezone
            return

        self.name = os.getenv("AVATAR_NAME") or self.name
        self.timezone = os.getenv("AVATAR_TIMEZONE") or self.timezone
        self.work_dir = os.getenv("AVATAR_WORK_DIR") or self.work_dir

        # Set environment variables based on the configuration
        if self.timezone:
            os.environ["AVATAR_TIMEZONE"] = self.timezone

        root = (
            pathlib.Path(self.work_dir).expanduser() / self.id
            if self.work_dir.strip()
            else default_work_dir(self.id)
        )

        workspace = WorkspacePaths.from_root(root)
        prepare_workspace(workspace)

        self.work_dir = str(workspace.root)
        os.environ["AVATAR_WORK_DIR"] = self.work_dir
