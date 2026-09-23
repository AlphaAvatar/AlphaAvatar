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
"""Session-scoped Avatar runtime composition."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from alphaavatar.agents.utils.files.work_dirs import (
    WorkspacePaths,
    prepare_session_path,
    prepare_workspace,
)
from alphaavatar.core.output import OutputRuntime
from alphaavatar.core.perception import PerceptionRuntime
from alphaavatar.core.time import RuntimeClock
from alphaavatar.core.turn import TurnRuntime

from .capability import AvatarCapabilityRegistry
from .context_runtime import ContextRuntime
from .inference import InferenceExecutor
from .session_runtime import SessionRuntime

if TYPE_CHECKING:
    from alphaavatar.agents.configs.runtime_config import RuntimeConfig


@dataclass(slots=True, frozen=True)
class AvatarRuntime:
    """
    Session-scoped runtime composition root.

    Transport adapters and runtime plugins depend on this composition, while
    core runtimes remain independent from LiveKit and provider implementations.
    """

    clock: RuntimeClock
    workspace: WorkspacePaths

    # core-level
    perception: PerceptionRuntime
    turn: TurnRuntime
    output: OutputRuntime

    # agent-level
    session: SessionRuntime
    context: ContextRuntime

    inference: InferenceExecutor

    capability_registry: AvatarCapabilityRegistry = field(default_factory=AvatarCapabilityRegistry)

    def __post_init__(self) -> None:
        session_id = self.session.session_id

        if session_id != self.perception.session_id:
            raise ValueError(
                "SessionRuntime and PerceptionRuntime session IDs differ: "
                f"session={session_id!r}, perception={self.perception.session_id!r}"
            )

        if session_id != self.output.session_id:
            raise ValueError(
                "SessionRuntime and OutputRuntime session IDs differ: "
                f"session={session_id!r}, output={self.output.session_id!r}"
            )

        if self.perception.clock is not self.clock:
            raise ValueError("PerceptionRuntime must use AvatarRuntime.clock")

        if self.output.clock is not self.clock:
            raise ValueError("OutputRuntime must use AvatarRuntime.clock")

        if self.turn.perception is not self.perception:
            raise ValueError("TurnRuntime must use AvatarRuntime.perception")

    @classmethod
    def create(
        cls,
        *,
        workspace: WorkspacePaths,
        session: SessionRuntime,
        context: ContextRuntime,
        config: RuntimeConfig,
        inference: InferenceExecutor | None = None,
    ) -> AvatarRuntime:
        clock = RuntimeClock()
        session_id = session.session_id

        prepare_workspace(workspace)

        session_path = workspace.data.sessions.get(
            session.session_id,
            session.created_at.date(),
        )
        prepare_session_path(session_path)
        session.bind_path(session_path)

        perception = PerceptionRuntime(
            session_id=session_id,
            stream_maxlens=config.perception.build_stream_maxlens(),
            clock=clock,
        )

        turn = TurnRuntime(
            perception=perception,
            max_snapshots=config.turn.snapshot_maxlen,
            event_maxlen=config.turn.event_maxlen,
            context_ready_timeout_sec=config.turn.context_ready_timeout_sec,
        )

        return cls(
            clock=clock,
            workspace=workspace,
            session=session,
            context=context,
            perception=perception,
            turn=turn,
            output=OutputRuntime(session_id=session_id, clock=clock),
            inference=inference or InferenceExecutor.from_env(),
        )

    async def aclose(self) -> None:
        await self.output.aclose()
        await self.inference.close()
