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
from collections.abc import Callable
from typing import Any

from alphaavatar.agents.avatar.loop.enums import LoopEventKind, LoopState
from alphaavatar.agents.avatar.loop.schemas import EventSink, LoopEvent, LoopIdentity
from alphaavatar.core.cleanup import wait_for_cleanup

logger = logging.getLogger(__name__)


class LoopFeedback:
    """Direct async delivery: no second token queue, no model used for filler generation."""

    def __init__(
        self,
        identity: LoopIdentity,
        sink: EventSink | None,
        is_current: Callable[[], bool],
        *,
        delay: float,
        timeout: float,
    ) -> None:
        self.identity = identity
        self.state = LoopState.ACCEPTED
        self.model_step = 0
        self.tool_round = 0
        self._sink = sink
        self._is_current = is_current
        self._delay = delay
        self._timeout = timeout
        self._sequence = 0
        self._notice: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def emit(self, kind: LoopEventKind, **fields: Any) -> None:
        if self._sink is None or not self._is_current():
            return
        async with self._lock:
            if not self._is_current():
                return
            self._sequence += 1
            event = LoopEvent(
                identity=self.identity,
                sequence=self._sequence,
                kind=kind,
                state=self.state,
                model_step=self.model_step,
                tool_round=self.tool_round,
                **fields,
            )
            async with asyncio.timeout(self._timeout):
                await self._sink(event)

    async def visible(self, kind: LoopEventKind, **fields: Any) -> None:
        await self.cancel_notice()
        await self.emit(kind, **fields)

    async def change(self, state: LoopState, *, reason: str | None = None) -> None:
        await self.cancel_notice()
        self.state = state
        await self.emit(LoopEventKind.STATE, reason=reason)
        if state in {LoopState.MODEL, LoopState.TOOLS, LoopState.FINALIZING} and self._sink:
            self._notice = asyncio.create_task(self._wait_notice(), name="loop_wait_notice")

    async def _wait_notice(self) -> None:
        try:
            await asyncio.sleep(self._delay)
            await self.emit(LoopEventKind.WAITING)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Loop wait feedback failed")

    async def cancel_notice(self) -> None:
        task, self._notice = self._notice, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def aclose(self) -> None:
        task = asyncio.create_task(self.cancel_notice(), name="loop_feedback_close")
        await wait_for_cleanup(task)
