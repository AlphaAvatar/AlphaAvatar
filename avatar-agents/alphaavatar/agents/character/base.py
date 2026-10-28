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

from abc import abstractmethod
from dataclasses import dataclass, field

from alphaavatar.core.lifecycle import LifecycleComponent


@dataclass(frozen=True, slots=True)
class CharacterConnection:
    """A short-lived, scoped renderer attachment, not application credentials."""

    transport: str
    url: str
    agent_device_id: str
    device_id: str
    token: str = field(repr=False)

    def __post_init__(self) -> None:
        for name in ("transport", "url", "agent_device_id", "device_id", "token"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Character connection requires {name}")


class CharacterTransport(LifecycleComponent):
    """Host-supplied attachment; the renderer owns its lifecycle, never the shared room."""

    @property
    @abstractmethod
    def connection(self) -> CharacterConnection: ...

    @abstractmethod
    async def wait_ready(self) -> None: ...

    @abstractmethod
    async def wait_failed(self) -> None: ...


class VirtualCharacterSession(LifecycleComponent):
    """One presentation attachment. The renderer never owns model or audio generation."""

    @abstractmethod
    async def wait_failed(self) -> None: ...
