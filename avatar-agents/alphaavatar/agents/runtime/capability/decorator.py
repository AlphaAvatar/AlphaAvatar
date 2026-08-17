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
from .enum import AvatarCapabilityName
from .schema import AvatarCapability


def avatar_capability(*, name: AvatarCapabilityName, description: str):
    description = description.strip()
    if not description:
        raise ValueError(f"Avatar capability {name!r} requires a description.")

    capability = AvatarCapability(name=name, description=description)

    def decorator(cls):
        capabilities = tuple(getattr(cls, "capabilities", ()))
        if any(c.name == name for c in capabilities):
            cls.capabilities = tuple(capability if c.name == name else c for c in capabilities)
        else:
            cls.capabilities = (capability, *capabilities)
        return cls

    return decorator
