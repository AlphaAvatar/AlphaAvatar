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
import uuid

from pydantic import BaseModel, Field

from alphaavatar.agents.utils.files.work_dirs import UserPath, UserPathSnapshot, mk_user_dirs


class SessionConfig(BaseModel):
    """Dataclass which contains all session-related configuration, which will creat for each session."""

    user_id: str = Field(
        default=uuid.uuid4().hex, description="User ID associated with the session."
    )
    session_id: str = Field(
        default=uuid.uuid4().hex, description="Session ID for the current session."
    )
    session_timeout: int = Field(
        default=300, description="Session timeout in seconds. Default is 300 seconds (5 minutes)."
    )

    user_path: UserPath = Field(
        default=None,
        description="Resolved filesystem paths for this user.",
    )

    def model_post_init(self, __context):
        work_dir = os.getenv("AVATAR_WORK_DIR", "")
        self.user_path = mk_user_dirs(work_dir, self.user_id)

    def update_user_id(self, user_id: str) -> tuple[str, UserPathSnapshot, UserPathSnapshot]:
        """
        Update session user_id and mutate user_path in place.

        Returns:
            old_user_id, old_user_path_snapshot, new_user_path_snapshot
        """
        old_user_id = self.user_id
        old_user_path = self.user_path.snapshot()

        self.user_id = user_id

        work_dir = os.getenv("AVATAR_WORK_DIR", "")
        new_user_path = mk_user_dirs(work_dir, self.user_id)

        # Important:
        # Mutate existing UserPath object in place, so plugins holding the same object
        # can see the updated path.
        self.user_path.update_from(new_user_path)

        return old_user_id, old_user_path, self.user_path.snapshot()
