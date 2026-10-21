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
        "reasoning": "Let me think that through.",
        "reasoning_simple": "Let me check that carefully.",
        "reasoning_moderate": "I'll weigh the main points before answering.",
        "reasoning_complex": "I'll work through the details before giving you a conclusion.",
        "tool_start": "I'm working on that operation.",
        "tool_error": "That operation did not return a confirmed result.",
        "tool_unknown": "I could not confirm whether that operation completed.",
        "failed": "I couldn't complete this request with the available results.",
    },
    "zh": {
        "reasoning": "我想一想再回答。",
        "reasoning_simple": "我仔细核对一下。",
        "reasoning_moderate": "我权衡一下几个关键点，再回答你。",
        "reasoning_complex": "我先把细节梳理清楚，再给你结论。",
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
