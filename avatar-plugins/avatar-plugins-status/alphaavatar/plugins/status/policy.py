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
import time

from alphaavatar.agents import AvatarModule
from alphaavatar.agents.status import (
    StatusEvent,
    StatusPolicyBase,
    StatusPolicyConfig,
    StatusPriority,
    StatusType,
    StatusVisibility,
)
from alphaavatar.agents.tools.deepresearch_api import DeepResearchOp

_AVATAR_ENGINE_SOURCE = "avatar_engine"
_LLM_SOURCE = "llm"


class DefaultStatusPolicy(StatusPolicyBase):
    def __init__(
        self,
        *,
        default_config: StatusPolicyConfig | None = None,
    ):
        self.default_config = default_config or StatusPolicyConfig()

        self._turn_started_at: float | None = None
        self._last_emit_at: float | None = None
        self._emitted_count: int = 0

    def start_turn(self) -> None:
        now = time.time()
        self._turn_started_at = now
        self._last_emit_at = None
        self._emitted_count = 0

    def get_delay_sec(self, event: StatusEvent) -> float:
        if self._is_immediate_event(event):
            return 0.0

        return self._get_config(event).delay_sec

    def should_emit(self, event: StatusEvent) -> bool:
        if event.visibility == StatusVisibility.SILENT:
            return False

        now = time.time()

        if self._turn_started_at is None:
            self.start_turn()

        config = self._get_config(event)

        if self._emitted_count >= config.max_events_per_turn:
            return False

        if event.priority == StatusPriority.HIGH:
            return True

        if self._is_immediate_event(event):
            return self._check_interval(now, config)

        if self._turn_started_at is not None:
            elapsed = now - self._turn_started_at
            if elapsed < config.delay_sec:
                return False

        return self._check_interval(now, config)

    def mark_emitted(self) -> None:
        self._last_emit_at = time.time()
        self._emitted_count += 1

    def _check_interval(self, now: float, config: StatusPolicyConfig) -> bool:
        if self._last_emit_at is None:
            return True

        return now - self._last_emit_at >= config.min_interval_sec

    def _is_immediate_event(self, event: StatusEvent) -> bool:
        if event.source == AvatarModule.DEEPRESEARCH:
            return event.type == StatusType.TOOL_START and event.stage in {
                DeepResearchOp.SEARCH,
                DeepResearchOp.RESEARCH,
                DeepResearchOp.SCRAPE,
                DeepResearchOp.DOWNLOAD,
            }

        if event.source == AvatarModule.MCP and event.stage == "parallel_tools":
            return True

        if event.source == AvatarModule.RAG and event.stage == "indexing":
            return True

        return False

    def _get_config(self, event: StatusEvent) -> StatusPolicyConfig:
        if event.source in {AvatarModule.MEMORY, AvatarModule.PERSONA}:
            return StatusPolicyConfig(
                delay_sec=999999,
                min_interval_sec=999999,
                max_events_per_turn=0,
                default_visibility=StatusVisibility.SILENT,
            )

        if event.source == AvatarModule.DEEPRESEARCH:
            return StatusPolicyConfig(
                delay_sec=0.0,
                min_interval_sec=5.0,
                max_events_per_turn=4,
            )

        if event.source == AvatarModule.MCP:
            return StatusPolicyConfig(
                delay_sec=1.0,
                min_interval_sec=5.0,
                max_events_per_turn=3,
            )

        if event.source == AvatarModule.RAG:
            return StatusPolicyConfig(
                delay_sec=1.0,
                min_interval_sec=5.0,
                max_events_per_turn=3,
            )

        if event.source == _AVATAR_ENGINE_SOURCE:
            return StatusPolicyConfig(
                delay_sec=1.5,
                min_interval_sec=6.0,
                max_events_per_turn=2,
            )

        if event.source == _LLM_SOURCE:
            return StatusPolicyConfig(
                delay_sec=0.0,
                min_interval_sec=6.0,
                max_events_per_turn=2,
            )

        return self.default_config
