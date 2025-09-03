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
from typing import Any

from alphaavatar.agents.avatar import BeforeGenContextRO, HookDecision, ObservableList, OpType

from .base import MemoryBase


async def memory_chat_context_watcher(
    memory: MemoryBase,
    session_id: str,
    chat_context: ObservableList,
    op: OpType,
    payload: dict[str, Any],
):
    """Watch chat context changes and update memory accordingly, which will be called after llm generate reply (no matter user message or assistant message)"""

    if op == OpType.INSERT:
        memory.add(session_id=session_id, chat_item=payload["value"])

    # TODO: Whether to permanently add memory content to the global context


async def memory_search_hook(
    memory: MemoryBase, session_id: str, ctx: BeforeGenContextRO
) -> HookDecision:
    if ctx.chat_ctx:
        chat_context = ctx.chat_ctx.copy()
        if ctx.new_message is not None:
            chat_context.insert(ctx.new_message)
        await memory.search(session_id=session_id, chat_context=chat_context.items)

    return HookDecision()
