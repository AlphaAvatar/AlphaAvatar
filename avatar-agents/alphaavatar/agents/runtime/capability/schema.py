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
from dataclasses import dataclass

from .enum import AvatarCapabilityName


@dataclass(frozen=True, slots=True)
class AvatarCapability:
    name: AvatarCapabilityName
    description: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, AvatarCapabilityName):
            raise TypeError("name must be an AvatarCapabilityName")
        if not isinstance(self.description, str):
            raise TypeError("description must be a string")

        description = self.description.strip()
        if not description:
            raise ValueError("description cannot be empty")

        object.__setattr__(self, "description", description)
