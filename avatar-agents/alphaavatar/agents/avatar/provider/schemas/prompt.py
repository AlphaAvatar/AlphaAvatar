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

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .model_input import ModelInput, ModelInputItem, ModelInputMessage, ModelRole, ModelTextPart


class ModelPromptMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: ModelRole
    template: str


class ModelInputSlot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    variable_name: str = Field(min_length=1)


class ModelPrompt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    messages: tuple[ModelPromptMessage | ModelInputSlot, ...]

    @classmethod
    def from_messages(
        cls, messages: Sequence[tuple[ModelRole | str, str] | ModelInputSlot]
    ) -> ModelPrompt:
        return cls(
            messages=tuple(
                item
                if isinstance(item, ModelInputSlot)
                else ModelPromptMessage(role=ModelRole(item[0]), template=item[1])
                for item in messages
            )
        )

    def render(self, payload: Mapping[str, Any]) -> ModelInput:
        items: list[ModelInputItem] = []
        realtime = None
        for index, template in enumerate(self.messages):
            if isinstance(template, ModelInputSlot):
                value = payload[template.variable_name]
                if not isinstance(value, ModelInput):
                    raise TypeError(f"Prompt slot {template.variable_name!r} requires ModelInput")
                if value.realtime is not None:
                    if realtime is not None:
                        raise ValueError("A prompt cannot merge multiple realtime snapshots")
                    realtime = value.realtime
                items.extend(value.items)
            else:
                items.append(
                    ModelInputMessage(
                        id=f"prompt:{index}",
                        role=template.role,
                        parts=(ModelTextPart(template.template.format_map(payload)),),
                    )
                )
        if len({item.id for item in items}) != len(items):
            raise ValueError("Rendered prompt contains duplicate item IDs")
        return ModelInput(items=tuple(items), realtime=realtime)
