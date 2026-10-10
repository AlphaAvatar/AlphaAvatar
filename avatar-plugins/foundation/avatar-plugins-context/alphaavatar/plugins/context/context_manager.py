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
import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from alphaavatar.agents.avatar.context import ContextManager
from alphaavatar.agents.avatar.context.schemas import ContextBuildRequest, ContextPrepareRequest
from alphaavatar.agents.avatar.provider.enums import ModelInputType
from alphaavatar.agents.avatar.provider.errors import ModelProtocolError
from alphaavatar.agents.avatar.provider.schemas import ModelInput
from alphaavatar.agents.avatar.provider.schemas.model_input import ModelInputItem
from alphaavatar.agents.avatar.vision import VisualFrameSelector
from alphaavatar.agents.constants import DEFAULT_SYSTEM_VALUE
from alphaavatar.agents.utils.time import ParticipantTimeContext, format_user_time
from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.env.enums import ObservationKind
from alphaavatar.core.perception import PerceptionTemporalAligner, TemporalAlignmentMode
from alphaavatar.core.time import RuntimeTimeRange

from .config import ContextConfig
from .context_builder import ContextBuilder
from .snapshot import snapshot_input
from .template import AvatarSysPromptTemplate, RuntimeStateTemplate

if TYPE_CHECKING:
    from alphaavatar.agents.configs import AvatarConfig
    from alphaavatar.agents.memory import MemoryBase
    from alphaavatar.agents.persona import PersonaBase
    from alphaavatar.agents.runtime import AvatarRuntime, StateRuntime
    from alphaavatar.core.turn import TurnSnapshot

logger = logging.getLogger(__name__)


class AvatarContextManager(ContextManager):
    """Runtime-owned facade; no run counters, active query handles or SDK state live here."""

    _OBSERVATION_KINDS = frozenset(
        {
            ObservationKind.VIDEO_FRAME,
            ObservationKind.SCREEN_FRAME,
            ObservationKind.SPEECH_SEGMENT,
            ObservationKind.TRANSCRIPT_SEGMENT,
            ObservationKind.TEXT_INPUT,
            ObservationKind.IMAGE_INPUT,
        }
    )

    def __init__(
        self, *, runtime: AvatarRuntime, avatar_config: AvatarConfig, config: ContextConfig
    ) -> None:
        self._runtime = runtime
        self._config = config
        self._vision = avatar_config.vision.model_copy(deep=True)
        self._alignment_policy = avatar_config.runtime.temporal_alignment.build_policy()
        self._introduction = avatar_config.avatar.introduction
        self._memory: MemoryBase | None = None
        self._persona: PersonaBase | None = None
        self._pending = 0
        self._work: set[asyncio.Task[ModelInput]] = set()
        self._close_task: asyncio.Task[None] | None = None

    @property
    def initial_instructions(self) -> str:
        self._ensure_open()
        persona = self._persona.persona_content if self._persona is not None else None
        return self._system_template(self._runtime.state).instructions(
            stable_persona=persona or self._runtime.state.user_persona or DEFAULT_SYSTEM_VALUE
        )

    @staticmethod
    def _observe(task: asyncio.Task[Any]) -> None:
        if not task.cancelled():
            task.exception()

    def _ensure_open(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("Context manager is closing or closed")

    def bind_sources(self, *, memory: MemoryBase, persona: PersonaBase) -> None:
        self._ensure_open()
        different = self._memory is not memory or self._persona is not persona
        if self._memory is not None and different:
            raise RuntimeError("Context sources are already bound to another Engine")
        if self._pending or self._work:
            raise RuntimeError("Cannot bind Context sources during preparation")
        self._memory, self._persona = memory, persona

    def _system_template(self, state: StateRuntime) -> AvatarSysPromptTemplate:
        return AvatarSysPromptTemplate(
            self._introduction,
            interaction_method=state.interaction_method,
            internal_capabilities=self._runtime.capability_registry.capabilities,
            stable_behavior_rules=self._config.behavior_rules,
        )

    def _state_snapshot(self) -> StateRuntime:
        state = self._runtime.state
        times = {}
        for identity, participant in self._runtime.session.participants.items():
            time = format_user_time(
                participant.user_time.timezone, participant.user_time.timezone_source
            )
            times[identity] = ParticipantTimeContext(
                participant_id=identity, user_id=participant.effective_user_id, user_time=time
            )

        # Read sources once. Preparing a query must not write to shared State or participants.
        memory = self._memory.memory_content if self._memory is not None else state.memory_content
        persona = self._persona.persona_content if self._persona is not None else state.user_persona
        return replace(
            state,
            participant_time=times,
            interaction_method=replace(
                state.interaction_method, notes=list(state.interaction_method.notes)
            ),
            memory_content=memory or DEFAULT_SYSTEM_VALUE,
            user_persona=persona or DEFAULT_SYSTEM_VALUE,
            turn_behavior_rules="\n".join((state.global_behavior_rules, state.turn_behavior_rules)),
        )

    def _compose(
        self,
        request: ContextPrepareRequest,
        snapshot: TurnSnapshot,
        system_prompt: str,
        runtime_context: str,
    ) -> ModelInput:
        events = snapshot.perception_events
        if self._vision.input_mode != ModelInputType.REALTIME:
            events = tuple(
                event
                for event in events
                if event.source_state is not None
                or (
                    event.observation is not None
                    and event.observation.kind in self._OBSERVATION_KINDS
                )
            )

        # Request-local helpers avoid races between concurrent preparation workers.
        alignment = PerceptionTemporalAligner(self._alignment_policy).align(
            events=events,
            time_range=RuntimeTimeRange(start=snapshot.started_at, end=snapshot.committed_at),
            source_states_at_start=snapshot.source_states_at_start,
            source_states_at_end=snapshot.source_states_at_commit,
            has_event_gap=snapshot.perception_gap,
            missed_event_count=snapshot.missed_perception_events,
            mode=(
                TemporalAlignmentMode.FIXED
                if self._vision.input_mode == ModelInputType.REALTIME
                else None
            ),
        )
        selection = VisualFrameSelector().select(alignment=alignment, config=self._vision)
        result = ContextBuilder().build(
            request=ContextBuildRequest(
                base_input=request.input,
                input_id=request.input_id,
                alignment=alignment,
                visual_selection=selection,
                model_input_type=self._vision.input_mode,
            ),
            system_prompt=system_prompt,
            runtime_context=runtime_context,
            contributions=request.contributions,
            query_scope=f"{request.context_id}:{request.turn_id}",
        )

        return snapshot_input(result.model_input)

    async def prepare(self, request: ContextPrepareRequest) -> ModelInput:
        self._ensure_open()
        if not isinstance(request, ContextPrepareRequest):
            raise TypeError("ContextManager requires ContextPrepareRequest")

        if self._pending + len(self._work) >= self._config.max_pending_preparations:
            raise RuntimeError("Context preparation capacity exhausted")

        self._pending += 1
        reserved = True
        try:
            request = replace(request, input=snapshot_input(request.input))
            snapshot = self._runtime.turn.get(request.input_id)
            if snapshot is None or snapshot.turn_id != request.turn_id:
                raise ValueError("Context input does not identify the requested committed turn")
            if request.context_id not in snapshot.context_ids:
                raise ValueError("Committed turn does not belong to the requested context")

            ready = await self._runtime.turn.wait_context_ready(snapshot)
            self._ensure_open()
            if request.context_id != self._runtime.state.context_id:
                raise ValueError("State no longer belongs to the requested context")
            if not ready:
                logger.debug("Context readiness timed out turn_id=%s", request.turn_id)

            state = self._state_snapshot()
            system = self._system_template(state).instructions(stable_persona=state.user_persona)
            text = RuntimeStateTemplate().render(state_runtime=state)
            task = asyncio.create_task(
                asyncio.to_thread(self._compose, request, snapshot, system, text),
                name=f"context_prepare:{request.turn_id}",
            )
            self._work.add(task)
            self._pending -= 1
            reserved = False
            task.add_done_callback(self._work.discard)
            task.add_done_callback(self._observe)

            # Cancellation drops this request's delivery, not ownership of an in-flight worker.
            result = await asyncio.shield(task)
            self._ensure_open()
            return result
        finally:
            if reserved:
                self._pending -= 1

    def build(
        self, prefix: ModelInput, *, continuation: tuple[ModelInputItem, ...] = ()
    ) -> ModelInput:
        self._ensure_open()
        if not isinstance(prefix, ModelInput):
            raise TypeError("ContextManager requires a captured ModelInput")

        identities = {item.id for item in prefix.items}
        added = {item.id for item in continuation}

        if len(identities) != len(prefix.items) or len(added) != len(continuation):
            raise ModelProtocolError("Context contains duplicate item identities")

        if identities.intersection(added):
            raise ModelProtocolError("Context continuation overlaps its captured prefix")

        if any(ContextBuilder._is_runtime_context_item(item) for item in continuation):
            raise ModelProtocolError("Runtime context is not canonical execution history")

        return replace(prefix, items=(*prefix.items, *continuation))

    async def _close(self) -> None:
        await asyncio.gather(*tuple(self._work), return_exceptions=True)
        self._work.clear()
        self._memory = self._persona = None

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="context_manager_close")
        await wait_for_cleanup(self._close_task)
