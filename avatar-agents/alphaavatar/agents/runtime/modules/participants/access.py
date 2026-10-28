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

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class UserDataAccess:
    """Application-issued grants, independent of identity model and Agent decisions."""

    readable_users: frozenset[str] = field(default_factory=frozenset)
    writable_users: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        for name in ("readable_users", "writable_users"):
            values = frozenset(getattr(self, name))
            if any(not isinstance(value, str) or not value for value in values):
                raise ValueError("User data grants require nonempty user identifiers")
            object.__setattr__(self, name, values)

    def can_read_user(self, user_id: str) -> bool:
        return user_id in self.readable_users

    def can_write_user(self, user_id: str) -> bool:
        return user_id in self.writable_users
