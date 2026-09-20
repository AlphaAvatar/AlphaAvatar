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

from pydantic import BaseModel, Field

from alphaavatar.agents.utils.files.work_dirs import (
    WorkspacePaths,
    default_work_dir,
    prepare_workspace,
)


class AvatarInfoConfig(BaseModel):
    """Configuration for the prompt used in the agent, , which will creat when server load."""

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
        # Get Global environment variables
        # BUG: The first time, you might get:
        # BUG: data/avatar-id
        # BUG: If `AvatarInfoConfig` is instantiated again within the same process, the environment variable is already:
        # BUG: /data/avatar-id
        # BUG: It might then be concatenated again to form:
        # BUG: /data/avatar-id/avatar-id

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
