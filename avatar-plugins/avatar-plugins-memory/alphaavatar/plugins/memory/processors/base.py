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

from typing import TYPE_CHECKING

from livekit.agents.llm import ChatItem

from alphaavatar.agents.memory import MemoryProcessorBase
from alphaavatar.agents.runtime import AvatarRuntime

if TYPE_CHECKING:
    from ..runtime import MemoryRuntime
    from ..state import MemoryContextState


class MemoryProcessor(MemoryProcessorBase):
    def __init__(self, *, runtime: AvatarRuntime, memory: MemoryRuntime) -> None:
        super().__init__(runtime=runtime, memory=memory)
        self._memory_runtime = memory

    @property
    def memory_runtime(self) -> MemoryRuntime:
        return self._memory_runtime

    def on_message(self, *, state: MemoryContextState, chat_item: ChatItem) -> None:
        pass

    async def update(self, state: MemoryContextState) -> None:
        pass

    async def _start(self) -> None:
        pass

    async def _stop(self, *, finalize: bool) -> None:
        pass
