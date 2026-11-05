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

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..module import AvatarModule, AvatarModulePlugin


@dataclass(frozen=True, slots=True)
class ResolvedPlugin:
    module: AvatarModule
    name: str
    factory: AvatarModulePlugin
    distribution: str | None  # The installed package whose entry point names it.

    @property
    def namespace(self) -> str:
        """Its package's name, which its storage and runner settings use: ``memory`` for
        ``alphaavatar.plugins.memory``."""
        parts = type(self.factory).__module__.split(".")
        return parts[2] if parts[:2] == ["alphaavatar", "plugins"] else parts[0]
