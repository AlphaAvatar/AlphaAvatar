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

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from alphaavatar.agents.avatar.provider.enums import ModelInputType
from alphaavatar.agents.avatar.provider.schemas import ModelInput
from alphaavatar.agents.avatar.vision import VisualFrameSelector
from alphaavatar.agents.constants import DEFAULT_SYSTEM_VALUE
from alphaavatar.agents.utils.time import ParticipantTimeContext, format_user_time
from alphaavatar.core.env import ObservationKind
from alphaavatar.core.perception import PerceptionTemporalAligner, TemporalAlignmentMode
from alphaavatar.core.time import RuntimeTimeRange
from alphaavatar.core.turn import TurnSnapshot

from .context_builder import ContextBuilder
from .schemas import (
    ContextBuildRequest,
    ContextBuildResult,
    ContextContribution,
    ContextPrepareRequest,
    PreparedModelContext,
)
from .template import AvatarSysPromptTemplate, RuntimeStateTemplate

if TYPE_CHECKING:
    from alphaavatar.agents.configs import AvatarConfig
    from alphaavatar.agents.memory import MemoryBase
    from alphaavatar.agents.persona import PersonaBase
    from alphaavatar.agents.runtime import AvatarRuntime


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AvatarContext:
    model_input: ModelInput
    input_kind: str | None
    turn_snapshot: TurnSnapshot


class AvatarContextManager:
    _MODEL_OBSERVATION_KINDS = {
        ObservationKind.VIDEO_FRAME,
        ObservationKind.SCREEN_FRAME,
        ObservationKind.SPEECH_SEGMENT,
        ObservationKind.TRANSCRIPT_SEGMENT,
        ObservationKind.TEXT_INPUT,
        ObservationKind.IMAGE_INPUT,
    }

    def __init__(
        self,
        *,
        avatar_config: AvatarConfig,
        runtime: AvatarRuntime,
        memory: MemoryBase,
        persona: PersonaBase,
    ) -> None:
        self._avatar_config = avatar_config
        self._runtime = runtime
        self._memory = memory
        self._persona = persona

        self._temporal_aligner = PerceptionTemporalAligner(
            avatar_config.runtime.temporal_alignment.build_policy()
        )
        self._visual_selector = VisualFrameSelector()
        self._system_template = AvatarSysPromptTemplate(
            avatar_config.avatar.introduction,
            interaction_method=runtime.state.interaction_method,
            internal_capabilities=runtime.capability_registry.capabilities,
            stable_behavior_rules=runtime.state.global_behavior_rules,
        )
        self._runtime_state_template = RuntimeStateTemplate()
        self._context_builder = ContextBuilder()

    @property
    def initial_instructions(self) -> str:
        return self._system_template.instructions(
            stable_persona=self._persona.persona_content or DEFAULT_SYSTEM_VALUE
        )

    def _events_for_model(self, turn_snapshot: TurnSnapshot):
        if self._avatar_config.vision.input_mode == ModelInputType.REALTIME:
            return turn_snapshot.perception_events

        return tuple(
            event
            for event in turn_snapshot.perception_events
            if event.source_state is not None
            or (
                event.observation is not None
                and event.observation.kind in self._MODEL_OBSERVATION_KINDS
            )
        )

    def _refresh_runtime_context(self) -> None:
        state = self._runtime.state

        participant_time: dict[str, ParticipantTimeContext] = {}
        for participant_id, participant in self._runtime.session.participants.items():
            participant.user_time = format_user_time(
                participant.user_time.timezone,
                participant.user_time.timezone_source,
            )

            participant_time[participant_id] = ParticipantTimeContext(
                participant_id=participant_id,
                user_id=participant.effective_user_id,
                user_time=participant.user_time,
            )

        state.participant_time = participant_time
        state.user_persona = self._persona.persona_content or DEFAULT_SYSTEM_VALUE
        state.memory_content = self._memory.memory_content or DEFAULT_SYSTEM_VALUE
        state.plan_content = state.plan_content or DEFAULT_SYSTEM_VALUE
        state.reflection_content = state.reflection_content or DEFAULT_SYSTEM_VALUE
        state.turn_behavior_rules = state.turn_behavior_rules or DEFAULT_SYSTEM_VALUE

    def build(
        self,
        base_input: ModelInput,
        *,
        turn_snapshot: TurnSnapshot,
        contributions: tuple[ContextContribution, ...] = (),
        query_scope: str = "",
    ) -> AvatarContext:
        self._refresh_runtime_context()

        alignment = self._temporal_aligner.align(
            events=self._events_for_model(turn_snapshot),
            time_range=RuntimeTimeRange(
                start=turn_snapshot.started_at,
                end=turn_snapshot.committed_at,
            ),
            source_states_at_start=turn_snapshot.source_states_at_start,
            source_states_at_end=turn_snapshot.source_states_at_commit,
            has_event_gap=turn_snapshot.perception_gap,
            missed_event_count=turn_snapshot.missed_perception_events,
            mode=(
                TemporalAlignmentMode.FIXED
                if self._avatar_config.vision.input_mode == ModelInputType.REALTIME
                else None
            ),
        )

        visual_selection = self._visual_selector.select(
            alignment=alignment,
            config=self._avatar_config.vision,
        )

        context: ContextBuildResult = self._context_builder.build(
            request=ContextBuildRequest(
                base_input=base_input,
                input_id=turn_snapshot.input_id,
                alignment=alignment,
                visual_selection=visual_selection,
                model_input_type=self._avatar_config.vision.input_mode,
            ),
            system_prompt=self._system_template.instructions(
                stable_persona=self._runtime.state.user_persona
            ),
            runtime_context=self._runtime_state_template.render(state_runtime=self._runtime.state),
            contributions=contributions,
            query_scope=query_scope or turn_snapshot.turn_id,
        )

        return AvatarContext(
            model_input=context.model_input,
            input_kind=base_input.latest_input_kind,
            turn_snapshot=turn_snapshot,
        )

    async def prepare(self, request: ContextPrepareRequest) -> PreparedModelContext:
        """Resolve one committed input, capture once, then hand ownership to the execution."""
        snapshot = self._runtime.turn.get(request.input_id)
        if snapshot is None or snapshot.turn_id != request.turn_id:
            raise ValueError("Context input does not identify the requested committed turn")

        if request.context_id not in snapshot.context_ids:
            raise ValueError("The committed turn does not belong to the requested context")

        ready = await self._runtime.turn.wait_context_ready(snapshot)
        if not ready:
            logger.debug("Turn context readiness timed out turn_id=%s", snapshot.turn_id)
        if request.context_id != self._runtime.state.context_id:
            raise ValueError("State no longer belongs to the requested context")

        context = self.build(
            request.input,
            turn_snapshot=snapshot,
            contributions=request.contributions,
            query_scope=f"{request.context_id}:{request.turn_id}",
        )

        return PreparedModelContext(context.model_input)
