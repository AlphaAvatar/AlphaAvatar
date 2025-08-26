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
import types

from livekit.agents import llm

from alphaavatar.agents.memory import MemoryBase


def add_message_wrapper(*, session_id, _chat_ctx: llm.ChatContext, _memory: MemoryBase):
    orig_add_message = _chat_ctx.add_message

    def wrapper(self, *args, **kwargs):
        message: llm.ChatMessage = orig_add_message(*args, **kwargs)
        print(message, "((---))", flush=True)

        # post-process: add message to memory
        _memory.add(session_id=session_id, chat_item=message)

        return message

    return types.MethodType(wrapper, _chat_ctx)
