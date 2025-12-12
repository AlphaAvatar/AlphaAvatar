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
import uuid

from pydantic import BaseModel, Field


class SessionConfig(BaseModel):
    """Dataclass which contains all session-related configuration."""

    user_id: str = Field(default=uuid.uuid4().hex)
    """User ID associated with the session."""
    session_id: str = Field(default=uuid.uuid4().hex)
    """Session ID for the current session."""
    session_timeout: int = Field(default=300)
    """Session timeout in seconds. Default is 300 seconds (5 minutes)."""
