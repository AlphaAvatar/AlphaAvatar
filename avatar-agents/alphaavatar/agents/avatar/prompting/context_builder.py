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

from dataclasses import dataclass
from typing import TYPE_CHECKING

from alphaavatar.agents.avatar.vision import VisualFrameSelector
from alphaavatar.agents.configs import AvatarConfig
from alphaavatar.agents.constants import DEFAULT_SYSTEM_VALUE
from alphaavatar.agents.providers.schema import (
    ModelInput,
    ModelInputType,
)
from alphaavatar.agents.runtime import TurnSnapshot
from alphaavatar.agents.utils import format_current_time
from alphaavatar.core.env import ObservationKind
from alphaavatar.core.perception import (
    PerceptionTemporalAligner,
    TemporalAlignmentMode,
)
from alphaavatar.core.time import RuntimeTimeRange

from .manager import PromptManager
from .renderer import PromptRenderRequest
from .template import AvatarSysPromptTemplate, RuntimeContextTemplate

if TYPE_CHECKING:
    from alphaavatar.agents.memory import MemoryBase
    from alphaavatar.agents.persona import PersonaBase
    from alphaavatar.agents.runtime import ContextRuntime


@dataclass(frozen=True, slots=True)
class AgentContext:
    model_input: ModelInput
    input_kind: str | None
    turn_snapshot: TurnSnapshot


class AgentContextBuilder:
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
        context_runtime: ContextRuntime,
        memory: MemoryBase,
        persona: PersonaBase,
    ) -> None:
        self._avatar_config = avatar_config
        self._context_runtime = context_runtime
        self._memory = memory
        self._persona = persona

        self._temporal_aligner = PerceptionTemporalAligner(
            avatar_config.runtime.temporal_alignment.build_policy()
        )
        self._visual_selector = VisualFrameSelector()
        self._system_template = AvatarSysPromptTemplate(
            avatar_config.avatar.introduction,
            interaction_method=context_runtime.interaction_method,
            stable_behavior_rules=context_runtime.global_behavior_rules,
        )
        self._runtime_context_template = RuntimeContextTemplate()
        self._prompt_manager = PromptManager()

    @property
    def initial_instructions(self) -> str:
        return self._system_template.instructions(
            stable_persona=(self._persona.persona_content or DEFAULT_SYSTEM_VALUE)
        )

    def _events_for_model(
        self,
        turn_snapshot: TurnSnapshot,
    ):
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
        context = self._context_runtime

        context.timestamp = format_current_time(
            context.timestamp.timezone,
            context.timestamp.timezone_source,
        )
        context.user_persona = self._persona.persona_content or DEFAULT_SYSTEM_VALUE
        context.memory_content = self._memory.memory_content or DEFAULT_SYSTEM_VALUE
        context.plan_content = context.plan_content or DEFAULT_SYSTEM_VALUE
        context.reflection_content = context.reflection_content or DEFAULT_SYSTEM_VALUE
        context.turn_behavior_rules = context.turn_behavior_rules or DEFAULT_SYSTEM_VALUE

    def build(
        self,
        base_input: ModelInput,
        *,
        turn_snapshot: TurnSnapshot,
    ) -> AgentContext:
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

        rendered = self._prompt_manager.render(
            request=PromptRenderRequest(
                base_input=base_input,
                input_id=turn_snapshot.input_id,
                alignment=alignment,
                visual_selection=visual_selection,
                model_input_type=(self._avatar_config.vision.input_mode),
            ),
            system_prompt=self._system_template.instructions(
                stable_persona=(self._context_runtime.user_persona)
            ),
            runtime_context=self._runtime_context_template.render(
                context_runtime=self._context_runtime,
            ),
        )

        return AgentContext(
            model_input=rendered.model_input,
            input_kind=base_input.latest_input_kind,
            turn_snapshot=turn_snapshot,
        )
