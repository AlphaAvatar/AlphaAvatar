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
# Extraction prompts, split by memory domain. Re-exported here so callers keep
# a single import site.
from ..processors.conversation.fragments import SESSION_GATE_FRAGMENT
from ..processors.conversation.prompt import (
    CONVERSATION_DELTA_PROMPT,
    CONVERSATION_MEMORY_EXTRACT_PROMPT,
    build_conversation_delta_prompt,
)
from ..processors.environment.prompt import ENV_DELTA_PROMPT, ENV_MEMORY_EXTRACT_PROMPT
from ..processors.tool.prompt import TOOL_DELTA_PROMPT, TOOL_MEMORY_EXTRACT_PROMPT

__all__ = [
    "CONVERSATION_DELTA_PROMPT",
    "CONVERSATION_MEMORY_EXTRACT_PROMPT",
    "ENV_DELTA_PROMPT",
    "ENV_MEMORY_EXTRACT_PROMPT",
    "SESSION_GATE_FRAGMENT",
    "TOOL_DELTA_PROMPT",
    "TOOL_MEMORY_EXTRACT_PROMPT",
    "build_conversation_delta_prompt",
]
