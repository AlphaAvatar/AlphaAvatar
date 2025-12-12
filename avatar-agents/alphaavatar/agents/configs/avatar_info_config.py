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
import uuid

from pydantic import BaseModel, Field


class AvatarInfoConfig(BaseModel):
    """Configuration for the prompt used in the agent."""

    avatar_id: str = Field(
        default=uuid.uuid4().hex,
        description="Unique identifier for the avatar.",
    )
    avatar_name: str = Field(
        default="Assistant",
        description="Name of the avatar.",
    )
    avatar_introduction: str = Field(
        default="You are a helpful voice AI assistant.",
        description="Introduction of the avatar.",
    )
    avatar_timezone: str = Field(
        default="server local time",
        description="The time zone where the Avatar is deployed is used to align with the user's time zone for related task execution",
    )

    def model_post_init(self, __context):
        os.environ["AVATAR_TIMEZONE"] = self.avatar_timezone
