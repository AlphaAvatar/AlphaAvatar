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
from typing import TYPE_CHECKING
from uuid import uuid4

from alphaavatar.agents.status import StatusProcessorBase
from alphaavatar.core.output.enums.audience import OutputAudience
from alphaavatar.core.output.schemas.decision import OutputStatusDecision

from ...state import ActivityNotice, StatusState
from ...tasks import spawn
from .config import PresentationConfig

if TYPE_CHECKING:
    from alphaavatar.agents.runtime import AvatarRuntime

logger = logging.getLogger(__name__)


class PresentationProcessor(StatusProcessorBase):
    def __init__(
        self, runtime: AvatarRuntime, state: StatusState, config: PresentationConfig
    ) -> None:
        self._runtime, self._state, self._config = runtime, state, config
        self._task: asyncio.Task | None = None
        self._notice: asyncio.Task | None = None
        self._turn_id: str | None = None
        self._spoken = 0
        self._last_narration = 0.0

    def _valid(self, notice: ActivityNotice) -> bool:
        return self._state.current(notice.scope, notice.revision)

    async def _publish(
        self, notice: ActivityNotice, audience: OutputAudience, *, narration: str | None = None
    ) -> bool:
        if audience == OutputAudience.USER and not self._valid(notice):
            return False

        now = self._runtime.clock.now().monotonic_ns
        decision = OutputStatusDecision(
            decision_id=uuid4().hex,
            source_event_id=notice.source_event_id,
            scope=notice.scope,
            audience=audience,
            action=notice.action,
            state=notice.state,
            revision=notice.revision,
            expires_at_ns=now + int(self._config.decision_ttl * 1_000_000_000),
            narration_key=narration,
            tool_name=notice.tool_name,
            outcome=notice.outcome,
        )
        try:
            async with asyncio.timeout(self._config.publish_timeout):
                event = await self._runtime.output.publish_status(decision=decision)
            return event is not None
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Status decision could not be published")
            return False

    async def _later(self, notice: ActivityNotice) -> None:
        delay = 0.0 if notice.action in {"tool_error", "failed"} else self._config.waiting_delay
        delay = max(
            delay,
            self._last_narration
            + self._config.min_narration_interval
            - asyncio.get_running_loop().time(),
        )
        await asyncio.sleep(delay)
        if not self._valid(notice) or self._spoken >= self._config.max_narrations_per_turn:
            return
        if await self._publish(notice, OutputAudience.USER, narration=notice.narration_key):
            self._spoken += 1
            self._last_narration = asyncio.get_running_loop().time()

    async def _cancel_notice(self) -> None:
        task, self._notice = self._notice, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run(self) -> None:
        while True:
            notice = await self._state.pending.get()
            if self._config.system_decisions:
                await self._publish(notice, OutputAudience.SYSTEM)

            if not self._valid(notice):
                continue

            await self._cancel_notice()
            if notice.scope.turn_id != self._turn_id:
                self._turn_id, self._spoken = notice.scope.turn_id, 0
                self._last_narration = 0.0

            if notice.action not in {"turn_committed", "tools_pending"}:
                await self._publish(notice, OutputAudience.USER)

            if notice.narration_key and self._spoken < self._config.max_narrations_per_turn:
                self._notice = spawn(self._later(notice), name="status:narration_delay")

    async def start(self) -> None:
        if self._task is None:
            self._task = spawn(self._run(), name="status:presentation")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        await self._cancel_notice()
