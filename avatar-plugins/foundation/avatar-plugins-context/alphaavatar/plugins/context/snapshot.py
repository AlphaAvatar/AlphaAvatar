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

from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType
from typing import Any

from alphaavatar.agents.avatar.provider.errors import ModelProtocolError
from alphaavatar.agents.avatar.provider.schemas.model_input import (
    ModelControlItem,
    ModelFunctionCall,
    ModelFunctionOutput,
    ModelInput,
    ModelInputItem,
    ModelInputMessage,
    ModelTextPart,
)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze(item) for item in value)
    return value


def _snapshot(item: ModelInputItem) -> ModelInputItem:
    changes: dict[str, Any] = {}
    if isinstance(item, ModelInputMessage | ModelFunctionCall):
        changes["metadata"] = _freeze(item.metadata)

    if isinstance(item, ModelInputMessage | ModelFunctionOutput):
        changes["parts"] = tuple(
            replace(part, annotations=tuple(_freeze(value) for value in part.annotations))
            if isinstance(part, ModelTextPart)
            else part
            for part in item.parts
        )

    if isinstance(item, ModelControlItem):
        changes["data"] = _freeze(item.data)

    return replace(item, **changes) if changes else item


def snapshot_input(model_input: ModelInput) -> ModelInput:
    items = tuple(_snapshot(item) for item in model_input.items)
    if len({item.id for item in items}) != len(items):
        raise ModelProtocolError("Context input contains duplicate item identities")

    return replace(model_input, items=items)
