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

from livekit.agents.llm import ChatMessage, FunctionCall, FunctionCallOutput

from alphaavatar.agents.memory.enums.cache_type import MemoryCacheType
from alphaavatar.core.turn import TurnSnapshot

from .state import MemoryContextItem


class MemoryPluginsTemplate:
    @classmethod
    def apply_update_template(
        cls,
        chat_context: list[MemoryContextItem],
        cache_type: MemoryCacheType,
    ) -> str:
        blocks = []

        for item in chat_context:
            if isinstance(item, TurnSnapshot):
                if item.text:
                    blocks.append(f"### user:\n{item.text}")
            elif isinstance(item, ChatMessage):
                if cache_type == MemoryCacheType.SESSION_INTERACTION and item.role not in {
                    "user",
                    "assistant",
                }:
                    continue
                blocks.append(f"### {item.role}:\n{item.text_content or ''}")
            elif isinstance(item, FunctionCall):
                blocks.append(
                    f"### assistant call function [{item.name}]:\n"
                    f"Function arguments: {item.arguments}"
                )
            elif isinstance(item, FunctionCallOutput):
                blocks.append(f"### function [{item.name}] output:\n{item.output}")

        return "\n\n".join(blocks)
