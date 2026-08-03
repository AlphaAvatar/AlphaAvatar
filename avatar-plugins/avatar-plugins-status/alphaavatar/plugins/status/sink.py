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
import time
from hashlib import sha1
from typing import Any
from uuid import uuid4

from alphaavatar.agents import AvatarModule
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


class StatusVoiceOutput:
    """
    Convert selected status messages into AUDIO_SYNCED transient source text.

    This class only creates semantic message output. Router handles TTS and
    transport adapters handle actual delivery.
    """

    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        min_interval_sec: float = 1.2,
        max_events_per_turn: int = 3,
    ) -> None:
        self._runtime = runtime
        self._min_interval_sec = min_interval_sec
        self._max_events_per_turn = max_events_per_turn

        self._turn_id: str | None = None
        self._spoken_count = 0
        self._last_spoken_at_by_bucket: dict[str, float] = {}
        self._spoken_keys: set[tuple[Any, ...]] = set()

    async def start_turn(self, *, turn_id: str) -> None:
        self._turn_id = turn_id
        self._spoken_count = 0
        self._last_spoken_at_by_bucket.clear()
        self._spoken_keys.clear()
        await self._runtime.output.start_turn(turn_id=turn_id)

    async def emit(self, event: StatusEvent, text: str) -> str | None:
        interaction = self._runtime.context.interaction_method
        if not bool(getattr(interaction, "audio_output", False)):
            return None
        if not self._should_speak(event):
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

        now = time.monotonic()
        bucket = self._voice_bucket(event)
        self._last_spoken_at_by_bucket[bucket] = now
        self._spoken_count += 1
        self._spoken_keys.add(self._spoken_key(event))
        return output_id

    def _should_speak(self, event: StatusEvent) -> bool:
        if self._spoken_count >= self._max_events_per_turn:
            return False

        key = self._spoken_key(event)
        if key in self._spoken_keys:
            return False

        last_spoken_at = self._last_spoken_at_by_bucket.get(self._voice_bucket(event))
        return (
            last_spoken_at is None
            or time.monotonic() - last_spoken_at >= self._min_interval_for(event)
        )

    @staticmethod
    def _voice_bucket(event: StatusEvent) -> str:
        return str(event.source)

    def _min_interval_for(self, event: StatusEvent) -> float:
        if str(event.source) == AvatarModule.AVATAR_ENGINE:
            return 3.0
        if event.source in {AvatarModule.DEEPRESEARCH, AvatarModule.MCP, AvatarModule.RAG}:
            return 1.2
        return self._min_interval_sec

    def _spoken_key(self, event: StatusEvent) -> tuple[Any, ...]:
        return event.source, event.stage, event.type, self._semantic_key(event)

    @staticmethod
    def _semantic_key(event: StatusEvent) -> str | None:
        query = event.metadata.get("query")
        if isinstance(query, str) and query.strip():
            return StatusVoiceOutput._short_hash(query.strip())
        if event.message:
            return StatusVoiceOutput._short_hash(event.message.strip())

        url_count = event.metadata.get("url_count")
        if url_count is not None:
            return f"url_count:{url_count}"

        op = event.metadata.get("op")
        return str(op) if op is not None else None

    @staticmethod
    def _short_hash(text: str) -> str:
        return sha1(text.encode("utf-8")).hexdigest()[:12]


class RuntimeStatusSink(StatusSinkBase):
    """
    Publish semantic status actions and optional transient messages.

    STATUS contains only machine-readable state. Rendered text is not included
    in STATUS and cannot be consumed as a user-visible message by transports.
    """

    def __init__(self, *, runtime: AvatarRuntime, voice_output: StatusVoiceOutput) -> None:
        self._runtime = runtime
        self._voice_output = voice_output
        self._turn_id: str | None = None

    async def start_turn(self, *, turn_id: str) -> None:
        self._turn_id = turn_id
        await self._voice_output.start_turn(turn_id=turn_id)

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

        rendered_text = text.strip() if isinstance(text, str) and text.strip() else None
        if rendered_text:
            await self._voice_output.emit(event, rendered_text)
