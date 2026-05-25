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
import asyncio
import json
from typing import Any

from alphaavatar.agents.status import StatusEvent, StatusSinkBase

from .log import logger


class CompositeStatusSink(StatusSinkBase):
    def __init__(self, sinks: list[StatusSinkBase] | None = None) -> None:
        self._sinks = sinks or []

    def add_sink(self, sink: StatusSinkBase) -> None:
        self._sinks.append(sink)

    def bind_engine(self, engine: Any) -> None:
        for sink in self._sinks:
            sink.bind_engine(engine)

    async def emit(self, event: StatusEvent, text: str | None) -> None:
        if not self._sinks:
            return

        results = await asyncio.gather(
            *(sink.emit(event, text) for sink in self._sinks),
            return_exceptions=True,
        )

        for result in results:
            if isinstance(result, Exception):
                logger.warning("Status sink failed: %s", result)


class LoggerStatusSink(StatusSinkBase):
    async def emit(self, event: StatusEvent, text: str | None) -> None:
        logger.info(
            "agent status | source=%s stage=%s type=%s visibility=%s text=%s metadata=%s",
            event.source,
            event.stage,
            event.type,
            event.visibility,
            text,
            event.metadata,
        )


class LiveKitDataChannelStatusSink(StatusSinkBase):
    def __init__(
        self,
        *,
        topic: str = "agent.status",
        reliable: bool = True,
    ) -> None:
        self.topic = topic
        self.reliable = reliable
        self._engine: Any | None = None

    def bind_engine(self, engine: Any) -> None:
        self._engine = engine

    async def emit(self, event: StatusEvent, text: str | None) -> None:
        if self._engine is None:
            return

        session = getattr(self._engine, "session", None)
        if session is None:
            return

        room = getattr(session, "room", None)
        if room is None:
            return

        local_participant = getattr(room, "local_participant", None)
        if local_participant is None:
            return

        payload = {
            "type": "agent_status",
            "event": event.to_dict(),
            "text": text,
        }

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        publish_data = getattr(local_participant, "publish_data", None)
        if publish_data is None:
            logger.debug("LiveKit local_participant has no publish_data method.")
            return

        result = publish_data(
            data,
            reliable=self.reliable,
            topic=self.topic,
        )

        if asyncio.iscoroutine(result):
            await result
