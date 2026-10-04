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

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from alphaavatar.agents.avatar.provider.schemas import (
    ModelRequest,
    ProviderTaskConfig,
    ProviderTraceConfig,
)
from alphaavatar.agents.avatar.provider.schemas.stream import ModelStreamEvent

from .schemas import (
    LoopCommit,
    LoopEvent,
    ToolCallContext,
    ToolPolicy,
)

if TYPE_CHECKING:
    from alphaavatar.agents.runtime.capability.registry import AvatarCapabilityRegistry


EventSink = Callable[[LoopEvent], Awaitable[None]]
CommitSink = Callable[[LoopCommit], Awaitable[None]]
ToolAuthorizer = Callable[[ToolCallContext], Awaitable[bool]]


class ModelStreamSource(Protocol):
    def stream(
        self,
        config: ProviderTaskConfig,
        request: ModelRequest,
        *,
        trace: ProviderTraceConfig | None = None,
        task_name: str = "model.stream",
    ) -> AbstractAsyncContextManager[AsyncIterator[ModelStreamEvent]]: ...


@dataclass(frozen=True, slots=True)
class LoopDependencies:
    provider: ModelStreamSource
    capabilities: AvatarCapabilityRegistry

    on_event: EventSink | None = None
    commit: CommitSink | None = None
    authorize: ToolAuthorizer | None = None

    tool_policies: Mapping[str, ToolPolicy] = field(default_factory=dict)
    supported_reasoning_efforts: tuple[str, ...] = ()
