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

from typing import Any

from langchain_core.messages import AIMessage, ChatMessage, HumanMessage, SystemMessage

from alphaavatar.agents.avatar.provider.schemas import (
    ModelInput,
    ModelInputMessage,
    ModelRole,
    ModelTextPart,
    ProviderTaskConfig,
)


class LangChainTextInputAdapter:
    async def adapt(self, model_input: ModelInput, *, config: ProviderTaskConfig) -> list[Any]:
        if model_input.realtime is not None:
            raise ValueError("Realtime snapshots require a dedicated input adapter")

        messages = []
        for item in model_input.items:
            if not isinstance(item, ModelInputMessage):
                raise TypeError("The text task adapter accepts messages, not tool/control items")
            if any(not isinstance(part, ModelTextPart) for part in item.parts):
                raise TypeError("The text task adapter cannot discard non-text content")
            text = item.text or ""
            if item.role == ModelRole.SYSTEM:
                messages.append(SystemMessage(content=text))
            elif item.role == ModelRole.DEVELOPER:
                messages.append(ChatMessage(role="developer", content=text))
            elif item.role == ModelRole.ASSISTANT:
                messages.append(AIMessage(content=text))
            elif item.role == ModelRole.USER:
                messages.append(HumanMessage(content=text))
            else:
                raise ValueError(f"Unsupported model role: {item.role!r}")

        return messages
