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

import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any

from alphaavatar.agents.avatar.provider.errors import ModelProtocolError
from alphaavatar.agents.avatar.provider.schemas import (
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


@dataclass(frozen=True, slots=True)
class ContextContribution:
    """Query-static plugin data. Context, not the contributor, chooses message placement."""

    name: str
    content: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.name):
            raise ValueError("Context contribution names must be bounded XML-safe identifiers")
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("Context contribution content must be nonempty text")


@dataclass(frozen=True, slots=True)
class ContextPrepareRequest:
    input: ModelInput
    turn_id: str
    context_id: str
    input_id: str
    contributions: tuple[ContextContribution, ...] = ()

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value
            for value in (self.turn_id, self.context_id, self.input_id)
        ):
            raise ValueError("Context preparation requires turn, context and input identities")
        names = [item.name for item in self.contributions]
        if len(set(names)) != len(names):
            raise ValueError("Context contribution names must be unique")


@dataclass(frozen=True, slots=True)
class PreparedModelContext:
    """One captured query prefix. Builds only append execution items; they never read State."""

    prefix: ModelInput = field(repr=False)
    _identities: frozenset[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        prefix = replace(self.prefix, items=tuple(_snapshot(item) for item in self.prefix.items))
        identities = frozenset(item.id for item in prefix.items)
        if len(identities) != len(prefix.items):
            raise ModelProtocolError("Prepared context contains duplicate item identities")
        object.__setattr__(self, "prefix", prefix)
        object.__setattr__(self, "_identities", identities)

    def build(self, continuation: tuple[ModelInputItem, ...] = ()) -> ModelInput:
        identities = {item.id for item in continuation}
        if len(identities) != len(continuation) or identities.intersection(self._identities):
            raise ModelProtocolError("Context continuation contains duplicate item identities")
        return replace(self.prefix, items=(*self.prefix.items, *continuation))
