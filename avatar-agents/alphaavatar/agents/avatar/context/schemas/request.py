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
from dataclasses import dataclass

from alphaavatar.agents.avatar.provider.schemas import ModelInput


@dataclass(frozen=True, slots=True)
class ContextContribution:
    """Query-static data; only ContextManager decides how it enters the model input."""

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
        if not isinstance(self.input, ModelInput):
            raise TypeError("Context preparation requires ModelInput")
        if not all(
            isinstance(value, str) and value
            for value in (self.turn_id, self.context_id, self.input_id)
        ):
            raise ValueError("Context preparation requires turn, context and input identities")
        if any(not isinstance(item, ContextContribution) for item in self.contributions):
            raise TypeError("Expected ContextContribution")
        names = [item.name for item in self.contributions]
        if len(set(names)) != len(names):
            raise ValueError("Context contribution names must be unique")
