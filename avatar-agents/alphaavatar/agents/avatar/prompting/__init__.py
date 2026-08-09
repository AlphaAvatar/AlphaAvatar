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
from .context_builder import AgentContext, AgentContextBuilder
from .context_status import AgentContextStatus, extract_answer_text
from .manager import PromptManager
from .renderer import (
    PromptRenderer,
    PromptRendererRegistry,
    PromptRenderRequest,
    PromptRenderResult,
    RealtimeRenderer,
    TextRenderer,
    VLMRenderer,
)
from .template import AvatarSysPromptTemplate, RuntimeContextTemplate

__all__ = [
    "AvatarSysPromptTemplate",
    "AgentContext",
    "AgentContextBuilder",
    "AgentContextStatus",
    "PreparedModelCall",
    "PromptManager",
    "PromptRenderRequest",
    "PromptRenderResult",
    "PromptRenderer",
    "PromptRendererRegistry",
    "RealtimeRenderer",
    "RuntimeContextTemplate",
    "TextRenderer",
    "VLMRenderer",
    "extract_answer_text",
]
