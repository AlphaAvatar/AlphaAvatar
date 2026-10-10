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
import inspect
import json
import logging
from typing import Any

from livekit import rtc

from alphaavatar.core.output import OutputRuntime, OutputSubscription
from alphaavatar.core.output.enums import OutputKind, OutputLane
from alphaavatar.core.output.enums.audience import OutputAudience
from alphaavatar.core.output.schemas import OutputEvent
from alphaavatar.core.output.schemas.decision import OutputStatusDecision

logger = logging.getLogger(__name__)


class LiveKitStatusOutput:
    """Transmit only user presentation decisions, never raw execution or record payloads."""

    def __init__(
        self,
        *,
        room: rtc.Room,
        output_runtime: OutputRuntime,
        action_topic: str = "agent.status.action",
        reliable: bool = True,
        subscription_name: str = "livekit:status_output",
    ) -> None:
        if not action_topic:
            raise ValueError("LiveKit status action_topic cannot be empty")

        self._room, self._output = room, output_runtime
        self._action_topic, self._reliable = action_topic, reliable
        self._subscription_name = subscription_name
        self._subscription: OutputSubscription | None = None
        self._run_task: asyncio.Task | None = None

    async def _publish_data(self, payload: dict[str, Any], *, topic: str) -> None:
        participant = getattr(self._room, "local_participant", None)
        if participant is None:
            raise RuntimeError("LiveKit room has no local participant")

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        result = participant.publish_data(data, reliable=self._reliable, topic=topic)
        if inspect.isawaitable(result):
            await result

    async def _handle_event(self, event: OutputEvent) -> None:
        decision = event.payload
        if not isinstance(decision, OutputStatusDecision):
            return
        if decision.audience != OutputAudience.USER:
            return
        if not self._output.accepts_status(decision):
            return

        # Project an allow-list. Tool arguments, internal metadata and reasoning stay local.
        common = {"source": "status", "stage": decision.action, "status_type": decision.action}
        await self._publish_data(
            {
                "type": "agent_status_action",
                "decision_id": decision.decision_id,
                "revision": decision.revision,
                "terminal": decision.terminal,
                "turn_id": decision.scope.turn_id,
                "run_id": decision.scope.run_id,
                "event": {"type": decision.action, "source": "status", "stage": decision.action},
                "action": common,
            },
            topic=self._action_topic,
        )

    async def _run(self) -> None:
        while True:
            event = await self._subscription.get()
            try:
                await self._handle_event(event)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Status transport failed event_id=%s", event.event_id)

    async def on_session_start(self) -> None:
        if self._run_task is not None:
            return
        self._subscription = await self._output.stream.subscribe(
            self._subscription_name,
            kinds=(OutputKind.STATUS,),
            lanes=(OutputLane.STATUS,),
            max_pending=128,
            reliable=False,
        )
        self._run_task = asyncio.create_task(self._run(), name=self._subscription_name)

    async def on_session_stop(self) -> None:
        task, self._run_task = self._run_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if self._subscription is not None:
            await self._output.stream.unsubscribe(self._subscription_name)
            self._subscription = None
