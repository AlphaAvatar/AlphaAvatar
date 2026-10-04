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

from functools import cache
from importlib.metadata import entry_points
from typing import Any

from alphaavatar.agents.avatar.loop import AvatarLoopBase, LoopDependencies
from alphaavatar.agents.runtime.plugin import AvatarModule, AvatarModulePlugin


@cache
def _load_loop(name: str) -> None:
    matches = tuple(entry_points(group="alphaavatar.loop", name=name))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one installed loop {name!r}, found {len(matches)}")
    matches[0].load()


class LoopService:
    """Factory access only. Engines own returned loops and must close them before Foundation."""

    def __init__(self) -> None:
        self._closed = False

    def create(
        self, *, config: Any, dependencies: LoopDependencies, implementation: str = "realtime"
    ) -> AvatarLoopBase:
        if self._closed:
            raise RuntimeError("Loop service is closed")
        _load_loop(implementation)
        loop = AvatarModulePlugin.create(
            AvatarModule.LOOP, implementation, config=config, dependencies=dependencies
        )
        if not isinstance(loop, AvatarLoopBase):
            raise TypeError("A Loop plugin must return AvatarLoopBase")
        return loop

    def close(self) -> None:
        self._closed = True
