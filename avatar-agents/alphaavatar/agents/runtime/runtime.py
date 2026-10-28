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

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.env.schemas import PerceptionSourceRef
from alphaavatar.core.output import OutputRuntime
from alphaavatar.core.perception import PerceptionRuntime
from alphaavatar.core.session import Participant, SessionRuntime
from alphaavatar.core.time import RuntimeClock
from alphaavatar.core.turn import TurnRuntime
from alphaavatar.core.workspace import SessionPath, WorkspacePaths

from .capability import AvatarCapabilityRegistry
from .inference import InferenceExecutor
from .modules.foundation import FoundationRuntime
from .modules.participants import ParticipantBindings, UserDataAccess
from .modules.state import StateRuntime

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
    session_path: SessionPath

    # core-level
    session: SessionRuntime
    perception: PerceptionRuntime
    turn: TurnRuntime
    output: OutputRuntime

    # agent-level
    state: StateRuntime

    # lifecycle-level
    inference: InferenceExecutor
    timezone: str | None = None
    data_access: UserDataAccess = field(default_factory=UserDataAccess)
    participant_bindings: ParticipantBindings = field(default_factory=ParticipantBindings)
    foundation: FoundationRuntime | None = None

    # capability
    capability_registry: AvatarCapabilityRegistry = field(default_factory=AvatarCapabilityRegistry)

    _close_task: asyncio.Task[None] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        session_id = self.session.session_id

        if self.session_path.session_id != session_id:
            raise ValueError("Session path belongs to another session")
        if self.session.clock is not self.clock:
            raise ValueError("SessionRuntime must use AvatarRuntime.clock")

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
        session_path: SessionPath,
        state: StateRuntime,
        config: RuntimeConfig,
        inference: InferenceExecutor,
        foundation: FoundationRuntime | None = None,
        timezone: str | None = None,
        data_access: UserDataAccess | None = None,
        participant_bindings: ParticipantBindings | None = None,
    ) -> AvatarRuntime:
        """Compose activated resources without filesystem work or ambient configuration."""
        clock = session.clock
        session_id = session.session_id

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
            session_path=session_path,
            state=state,
            perception=perception,
            turn=turn,
            output=OutputRuntime(session_id=session_id, clock=clock),
            inference=inference,
            foundation=foundation,
            timezone=timezone,
            data_access=data_access if data_access is not None else UserDataAccess(),
            participant_bindings=(
                participant_bindings if participant_bindings is not None else ParticipantBindings()
            ),
        )

    def resolve_participant(
        self, transport_participant_id: str | None, *, source: PerceptionSourceRef | None = None
    ) -> Participant | None:
        participant_id = self.participant_bindings.resolve(transport_participant_id, source=source)
        return (
            self.session.get_participant(participant_id=participant_id)
            if participant_id is not None
            else None
        )

    def bind_foundation(self, foundation: FoundationRuntime) -> None:
        if self._close_task is not None:
            raise RuntimeError("AvatarRuntime is closing or closed")
        if self.foundation is not None:
            raise RuntimeError("FoundationRuntime is already bound to AvatarRuntime")
        if not isinstance(foundation, FoundationRuntime):
            raise TypeError("Expected FoundationRuntime")
        object.__setattr__(self, "foundation", foundation)

    async def _close(self) -> None:
        errors: list[Exception] = []
        steps = [("output", self.output.aclose), ("inference", self.inference.close)]
        if self.foundation is not None:
            steps.insert(0, ("foundation", self.foundation.aclose))
        for name, operation in steps:
            try:
                await operation()
            except asyncio.CancelledError as exc:
                error = RuntimeError(f"AvatarRuntime {name} cleanup was cancelled")
                error.__cause__ = exc
                errors.append(error)
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise ExceptionGroup("AvatarRuntime cleanup failed", errors)

    async def aclose(self) -> None:
        if self._close_task is None:
            object.__setattr__(
                self, "_close_task", asyncio.create_task(self._close(), name="avatar_runtime_close")
            )

        await wait_for_cleanup(self._close_task)
