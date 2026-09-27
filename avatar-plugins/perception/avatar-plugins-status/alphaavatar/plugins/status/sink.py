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
from uuid import uuid4

from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.status import StatusEvent, StatusSinkBase
from alphaavatar.core.output import OutputLane, OutputTextMode

from .log import logger


class CompositeStatusSink(StatusSinkBase):
    def __init__(self, sinks: list[StatusSinkBase] | None = None) -> None:
        self._sinks = sinks or []

    def add_sink(self, sink: StatusSinkBase) -> None:
        self._sinks.append(sink)

    async def start_turn(self, *, turn_id: str) -> None:
        if not self._sinks:
            return

        results = await asyncio.gather(
            *(sink.start_turn(turn_id=turn_id) for sink in self._sinks),
            return_exceptions=True,
        )

        for result in results:
            if isinstance(result, Exception):
                logger.warning("Status sink start_turn failed: %s", result)

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
            "agent status | source=%s stage=%s type=%s text=%s metadata=%s",
            event.source,
            event.stage,
            event.type,
            text,
            event.metadata,
        )


class StatusVoiceOutput(StatusSinkBase):
    """
    Convert selected status messages into AUDIO_SYNCED transient source text.

    This class only creates semantic message output. Router handles TTS and
    transport adapters handle actual delivery.
    """

    def __init__(self, *, runtime: AvatarRuntime) -> None:
        self._runtime = runtime
        self._turn_id: str | None = None

    async def start_turn(self, *, turn_id: str) -> None:
        self._turn_id = turn_id

    async def emit(self, event: StatusEvent, text: str) -> str | None:
        interaction = self._runtime.context.interaction_method
        if not bool(getattr(interaction, "audio_output", False)):
            return None

        rendered_text = text.strip() if isinstance(text, str) and text.strip() else None
        if not rendered_text:
            return None

        output_id = uuid4().hex
        published = await self._runtime.output.publish_text_chunk(
            text=text,
            output_id=output_id,
            turn_id=self._turn_id,
            lane=OutputLane.TRANSIENT,
            mode=OutputTextMode.AUDIO_SYNCED,
            replace_lane=True,
            is_final=True,
            metadata={
                "source": str(event.source),
                "stage": event.stage,
                "status_type": str(event.type),
                "status_event": event.to_dict(),
            },
        )
        if published is None:
            return None

        return output_id


class RuntimeStatusSink(StatusSinkBase):
    """
    Publish semantic status actions and optional transient messages.

    STATUS contains only machine-readable state. Rendered text is not included
    in STATUS and cannot be consumed as a user-visible message by transports.
    """

    def __init__(self, *, runtime: AvatarRuntime) -> None:
        self._runtime = runtime
        self._turn_id: str | None = None

    async def start_turn(self, *, turn_id: str) -> None:
        self._turn_id = turn_id

    async def emit(self, event: StatusEvent, text: str | None) -> None:
        event_payload = event.to_dict()

        await self._runtime.output.publish_status(
            turn_id=self._turn_id,
            payload={
                "event": event_payload,
                "action": {
                    "source": event_payload.get("source"),
                    "stage": event_payload.get("stage"),
                    "status_type": event_payload.get("type"),
                },
            },
            metadata={
                "source": str(event.source),
                "stage": event.stage,
                "status_type": str(event.type),
            },
        )
