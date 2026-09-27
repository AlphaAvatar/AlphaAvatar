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
"""LiveKit transport adapter for AlphaAvatar status actions."""

from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any

from alphaavatar.agents.log import logger
from alphaavatar.agents.runtime.plugin import AvatarRuntimePlugin
from alphaavatar.core.output import (
    OutputEvent,
    OutputKind,
    OutputLane,
    OutputRuntime,
    OutputSubscription,
)
from livekit import rtc


class LiveKitStatusOutput(AvatarRuntimePlugin):
    """Publish machine-readable status actions through LiveKit data packets."""

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

        self._room = room
        self._output = output_runtime
        self._action_topic = action_topic
        self._reliable = reliable
        self._subscription_name = subscription_name

        self._subscription: OutputSubscription | None = None
        self._run_task: asyncio.Task[None] | None = None

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
        logger.info("LiveKit status output started action_topic=%s", self._action_topic)

    async def on_session_stop(self) -> None:
        run_task = self._run_task
        self._run_task = None

        if run_task is not None and not run_task.done():
            run_task.cancel()
        if run_task is not None:
            await asyncio.gather(run_task, return_exceptions=True)

        if self._subscription is not None:
            await self._output.stream.unsubscribe(self._subscription_name)

        self._subscription = None
        logger.info("LiveKit status output stopped")

    async def _run(self) -> None:
        subscription = self._subscription
        if subscription is None:
            return

        try:
            while True:
                event = await subscription.get()

                try:
                    await self._handle_event(event)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Failed to publish status action event_id=%s sequence=%s",
                        event.event_id,
                        event.sequence,
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("LiveKit status output consumer stopped unexpectedly.")

    async def _handle_event(self, event: OutputEvent) -> None:
        payload = event.payload
        if not isinstance(payload, dict):
            return

        await self._publish_data(
            {
                "type": "agent_status_action",
                "event": payload.get("event"),
                "action": payload.get("action"),
            },
            topic=self._action_topic,
        )

    async def _publish_data(self, payload: dict[str, Any], *, topic: str) -> None:
        participant = getattr(self._room, "local_participant", None)
        if participant is None:
            raise RuntimeError("LiveKit room has no local participant")

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        result = participant.publish_data(data, reliable=self._reliable, topic=topic)

        if inspect.isawaitable(result):
            await result
