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

from alphaavatar.agents.utils.files.work_dirs import default_work_dir


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
    timezone: str = Field(
        default="server local time",
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
        self.name = os.getenv("AVATAR_NAME") or self.name
        self.timezone = os.getenv("AVATAR_TIMEZONE") or self.timezone
        self.work_dir = os.getenv("AVATAR_WORK_DIR") or self.work_dir

        # Set environment variables based on the configuration
        os.environ["AVATAR_TIMEZONE"] = self.timezone

        if self.work_dir and self.work_dir.strip():
            work_dir = pathlib.Path(self.work_dir) / self.id
        else:
            work_dir = default_work_dir(self.id)

        work_dir.mkdir(parents=True, exist_ok=True)
        os.environ["AVATAR_WORK_DIR"] = str(work_dir)
