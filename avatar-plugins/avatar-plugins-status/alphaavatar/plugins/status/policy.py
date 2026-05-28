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
from hashlib import sha1
from typing import Any

from alphaavatar.agents import AvatarModule
from alphaavatar.agents.status import (
    StatusEvent,
    StatusPolicyBase,
    StatusPolicyConfig,
    StatusPriority,
    StatusType,
)
from alphaavatar.agents.tools.deepresearch_api import DeepResearchOp


class DefaultStatusPolicy(StatusPolicyBase):
    def __init__(
        self,
        *,
        default_config: StatusPolicyConfig | None = None,
    ):
        self.default_config = default_config or StatusPolicyConfig()

        self._turn_started_at: float | None = None
        self._emitted_count: int = 0

        # Bucket-level interval control.
        # This prevents repeated statuses from the same source while avoiding
        # one source, such as thinking, blocking a more useful tool status.
        self._last_emit_at_by_bucket: dict[str, float] = {}

        # Event-level dedupe within one turn.
        self._emitted_keys: set[tuple[Any, ...]] = set()

    def start_turn(self) -> None:
        self._turn_started_at = time.time()
        self._emitted_count = 0
        self._last_emit_at_by_bucket.clear()
        self._emitted_keys.clear()

    def get_delay_sec(self, event: StatusEvent) -> float:
        if self._is_immediate_event(event):
            return 0.0

        return self._get_config(event).delay_sec

    def should_emit(self, event: StatusEvent) -> bool:
        now = time.time()

        if self._turn_started_at is None:
            self.start_turn()

        config = self._get_config(event)

        if config.max_events_per_turn <= 0:
            return False

        if self._emitted_count >= config.max_events_per_turn:
            return False

        if event.priority == StatusPriority.HIGH:
            return True

        if self._is_duplicate_event(event):
            return False

        if not self._is_immediate_event(event):
            elapsed = now - (self._turn_started_at or now)
            if elapsed < config.delay_sec:
                return False

        if not self._check_bucket_interval(event, now, config):
            return False

        return True

    def mark_emitted(self, event: StatusEvent | None = None) -> None:
        now = time.time()
        self._emitted_count += 1

        if event is None:
            return

        self._last_emit_at_by_bucket[self._bucket_key(event)] = now
        self._emitted_keys.add(self._event_key(event))

    def _is_immediate_event(self, event: StatusEvent) -> bool:
        if event.type == StatusType.READY:
            return True

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

    def _check_bucket_interval(
        self,
        event: StatusEvent,
        now: float,
        config: StatusPolicyConfig,
    ) -> bool:
        # Tool monologues are more useful than generic thinking.
        # Let tool start events break the avatar_engine thinking interval.
        bucket = self._bucket_key(event)
        last_emit_at = self._last_emit_at_by_bucket.get(bucket)

        if last_emit_at is None:
            return True

        return now - last_emit_at >= config.min_interval_sec

    def _bucket_key(self, event: StatusEvent) -> str:
        # Use source-level bucket by default.
        # This means avatar_engine thinking won't block deepresearch status.
        return str(event.source)

    def _event_key(self, event: StatusEvent) -> tuple[Any, ...]:
        return (
            event.source,
            event.stage,
            event.type,
            self._semantic_key(event),
        )

    def _is_duplicate_event(self, event: StatusEvent) -> bool:
        return self._event_key(event) in self._emitted_keys

    def _semantic_key(self, event: StatusEvent) -> str | None:
        if event.source == AvatarModule.DEEPRESEARCH:
            query = event.metadata.get("query")
            if isinstance(query, str) and query.strip():
                return self._short_hash(query.strip())

            url_count = event.metadata.get("url_count")
            if url_count is not None:
                return f"url_count:{url_count}"

            op = event.metadata.get("op")
            if op is not None:
                return str(op)

        # If a tool provides a monologue, different monologues should be allowed.
        # This helps cases like "I'll try another query."
        if event.message:
            return self._short_hash(event.message.strip())

        return None

    def _short_hash(self, text: str) -> str:
        return sha1(text.encode("utf-8")).hexdigest()[:12]

    def _get_config(self, event: StatusEvent) -> StatusPolicyConfig:
        if event.type == StatusType.READY:
            return StatusPolicyConfig(
                delay_sec=0.0,
                min_interval_sec=0.0,
                max_events_per_turn=10,
            )

        if event.source in {AvatarModule.MEMORY, AvatarModule.PERSONA}:
            return StatusPolicyConfig(
                delay_sec=999999,
                min_interval_sec=999999,
                max_events_per_turn=0,
            )

        if event.source == AvatarModule.DEEPRESEARCH:
            return StatusPolicyConfig(
                delay_sec=0.0,
                min_interval_sec=2.0,
                max_events_per_turn=6,
            )

        if event.source == AvatarModule.MCP:
            return StatusPolicyConfig(
                delay_sec=1.0,
                min_interval_sec=3.0,
                max_events_per_turn=4,
            )

        if event.source == AvatarModule.RAG:
            return StatusPolicyConfig(
                delay_sec=1.0,
                min_interval_sec=3.0,
                max_events_per_turn=4,
            )

        if event.source == AvatarModule.AVATAR_ENGINE:
            return StatusPolicyConfig(
                delay_sec=1.5,
                min_interval_sec=6.0,
                max_events_per_turn=1,
            )

        return self.default_config
