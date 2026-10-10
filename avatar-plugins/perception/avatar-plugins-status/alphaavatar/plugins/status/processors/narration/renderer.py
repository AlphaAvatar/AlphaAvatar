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
MESSAGES = {
    "en": {
        "thinking": "I'm checking that.",
        "finalizing": "I'm putting the results together.",
        "tool_start": "I'm working on that operation.",
        "tool_error": "That operation did not return a confirmed result.",
        "tool_unknown": "I could not confirm whether that operation completed.",
        "failed": "I couldn't complete this request with the available results.",
    },
    "zh": {
        "thinking": "我正在检查这个问题。",
        "finalizing": "我正在整理已有结果。",
        "tool_start": "我正在处理这一步操作。",
        "tool_error": "这次操作没有返回确认成功的结果。",
        "tool_unknown": "我还无法确认这次操作是否已经完成。",
        "failed": "目前的结果不足以完成这次请求。",
    },
}


class RuleNarrator:
    def __init__(self, language: str) -> None:
        self._messages = MESSAGES[language]

    async def render(self, key: str) -> str | None:
        # Future model narrators use this bounded, non-recursive interface, never AvatarLoop.
        return self._messages.get(key)
