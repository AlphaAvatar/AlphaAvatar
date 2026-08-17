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
from datetime import datetime

from pydantic import BaseModel


class UserRuntimeState(BaseModel):
    """
    Runtime/login/session state for a user.

    This is system-observed state, not LLM-extracted profile details.
    Persist this to local markdown, not vector DB.
    """

    # Current session state
    current_timezone: str | None = None
    current_login_at: datetime | None = None
    current_session_id: str | None = None
    current_room_type: str | None = None

    # Previous session state
    last_timezone: str | None = None
    last_login_at: datetime | None = None
    last_session_id: str | None = None
    last_room_type: str | None = None

    # Aggregate
    login_count: int = 0
