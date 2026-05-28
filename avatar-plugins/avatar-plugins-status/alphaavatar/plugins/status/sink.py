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
import time
from enum import StrEnum
from hashlib import sha1
from typing import TYPE_CHECKING, Any

from alphaavatar.agents import AvatarModule
from alphaavatar.agents.entrypoints.schema.room_type import RoomType
from alphaavatar.agents.status import LiveKitDataPublisherMixin, StatusEvent, StatusSinkBase

from .log import logger

if TYPE_CHECKING:
    from alphaavatar.agents.avatar.engine import AvatarEngine


class StatusDeliveryMode(StrEnum):
    TEXT = "text"
    VOICE = "voice"
    BOTH = "both"
    NONE = "none"


class CompositeStatusSink(StatusSinkBase):
    def __init__(self, sinks: list[StatusSinkBase] | None = None) -> None:
        self._sinks = sinks or []

    def add_sink(self, sink: StatusSinkBase) -> None:
        self._sinks.append(sink)

    def bind_engine(self, engine: Any) -> None:
        for sink in self._sinks:
            sink.bind_engine(engine)

    def start_turn(self) -> None:
        for sink in self._sinks:
            start_turn = getattr(sink, "start_turn", None)
            if callable(start_turn):
                start_turn()

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


class StatusActionEventSink(StatusSinkBase, LiveKitDataPublisherMixin):
    """
    Publish structured status action events.

    This is for UI components / avatar animation / client-side state machines.
    It does not mean "send a user-visible text message".
    """

    def __init__(
        self,
        *,
        topic: str = "agent.status.action",
        reliable: bool = True,
    ) -> None:
        self.topic = topic
        self.reliable = reliable
        self._engine: AvatarEngine | None = None

    def bind_engine(self, engine: AvatarEngine) -> None:
        self._engine = engine

    async def emit(self, event: StatusEvent, text: str | None) -> None:
        if self._engine is None:
            return

        # Only publish action events when there is an active client room.
        local_participant = self._get_local_participant()
        if local_participant is None:
            return

        payload = {
            "type": "agent_status_action",
            "event": event.to_dict(),
            "text": text,
            "action": self._to_action(event),
        }

        await self._publish_data(local_participant, payload, topic=self.topic)

    def _to_action(self, event: StatusEvent) -> dict[str, Any]:
        return {
            "source": event.to_dict().get("source"),
            "stage": event.to_dict().get("stage"),
            "status_type": event.to_dict().get("type"),
        }


class TextOrVoiceStatusSink(StatusSinkBase, LiveKitDataPublisherMixin):
    """
    Deliver short user-facing status through text and/or voice.

    Routing is decided by room type / interaction mode.
    Voice delivery has lightweight per-source throttling, so generic thinking
    does not block concrete tool progress.
    """

    def __init__(
        self,
        *,
        text_topic: str = "agent.status.text",
        reliable: bool = True,
        min_voice_interval_sec: float = 1.2,
        max_voice_events_per_turn: int = 3,
    ) -> None:
        self.text_topic = text_topic
        self.reliable = reliable
        self.min_voice_interval_sec = min_voice_interval_sec
        self.max_voice_events_per_turn = max_voice_events_per_turn

        self._engine: AvatarEngine | None = None

        self._voice_lock = asyncio.Lock()
        self._voice_tasks: set[asyncio.Task] = set()

        self._spoken_count: int = 0
        self._last_spoken_at_by_bucket: dict[str, float] = {}
        self._spoken_keys: set[tuple[Any, ...]] = set()

    def bind_engine(self, engine: AvatarEngine) -> None:
        self._engine = engine

    def start_turn(self) -> None:
        self._spoken_count = 0
        self._last_spoken_at_by_bucket.clear()
        self._spoken_keys.clear()

    async def emit(self, event: StatusEvent, text: str | None) -> None:
        if self._engine is None:
            return

        if not text:
            return

        mode = self._resolve_delivery_mode()

        if mode == StatusDeliveryMode.NONE:
            return

        if mode in {StatusDeliveryMode.TEXT, StatusDeliveryMode.BOTH}:
            await self._publish_text_status(
                event,
                text.strip(),
            )

        if mode in {StatusDeliveryMode.VOICE, StatusDeliveryMode.BOTH}:
            self._speak_nowait(
                event,
                text.strip(),
            )

    def _resolve_delivery_mode(self) -> StatusDeliveryMode:
        interaction = self._get_interaction_method()
        if interaction is None:
            return StatusDeliveryMode.NONE

        room_type = str(getattr(interaction, "room_type", "") or "")
        text_output = bool(getattr(interaction, "text_output", False))
        audio_output = bool(getattr(interaction, "audio_output", False))

        # Bridged text channels.
        if room_type in {
            RoomType.WHATSAPP.value,
            RoomType.TELEGRAM.value,
            RoomType.SLACK.value,
            RoomType.DISCORD.value,
        }:
            return StatusDeliveryMode.TEXT

        # API rooms usually should not speak.
        if room_type == RoomType.API.value:
            return StatusDeliveryMode.TEXT if text_output else StatusDeliveryMode.NONE

        # Generic fallback based on actual outputs.
        if text_output and audio_output:
            return StatusDeliveryMode.BOTH

        if text_output:
            return StatusDeliveryMode.TEXT

        if audio_output:
            return StatusDeliveryMode.VOICE

        return StatusDeliveryMode.NONE

    def _get_interaction_method(self):
        runtime_context = getattr(self._engine, "runtime_context", None)
        if runtime_context is None:
            return None

        return getattr(runtime_context, "interaction_method", None)

    async def _publish_text_status(self, event: StatusEvent, text: str) -> None:
        local_participant = self._get_local_participant()
        if local_participant is None:
            return

        payload = {
            "type": "agent_status_text",
            "event": event.to_dict(),
            "text": text,
        }

        await self._publish_data(local_participant, payload, topic=self.text_topic)

    def _speak_nowait(self, event: StatusEvent, text: str) -> None:
        if not self._should_speak(event):
            return

        task = asyncio.create_task(self._speak_safely(event, text))
        self._track_voice_task(task)

    def _should_speak(self, event: StatusEvent) -> bool:
        if self._spoken_count >= self.max_voice_events_per_turn:
            return False

        key = self._spoken_key(event)
        if key in self._spoken_keys:
            return False

        now = time.time()
        bucket = self._voice_bucket(event)

        last_spoken_at = self._last_spoken_at_by_bucket.get(bucket)
        if last_spoken_at is not None:
            if now - last_spoken_at < self._min_interval_for(event):
                return False

        return True

    async def _speak_safely(self, event: StatusEvent, text: str) -> None:
        async with self._voice_lock:
            try:
                await self._speak(text)

                now = time.time()
                self._last_spoken_at_by_bucket[self._voice_bucket(event)] = now
                self._spoken_count += 1
                self._spoken_keys.add(self._spoken_key(event))

            except Exception as e:
                logger.warning("Voice status speak failed: %s", e)

    async def _speak(self, text: str) -> None:
        if self._engine is None:
            return

        # Preferred explicit hook on AvatarEngine.
        speak_status_text = getattr(self._engine, "speak_status_text", None)
        if callable(speak_status_text):
            result = speak_status_text(
                text,
                allow_interruptions=True,
                add_to_chat_ctx=False,
            )
            if asyncio.iscoroutine(result):
                await result
            return

        logger.debug("TextOrVoiceStatusSink skipped voice because no safe TTS method was found.")

    def _voice_bucket(self, event: StatusEvent) -> str:
        # Generic thinking and concrete tool progress should not block each other.
        return str(event.source)

    def _min_interval_for(self, event: StatusEvent) -> float:
        # Generic thinking should not repeat too often.
        if str(event.source) == AvatarModule.AVATAR_ENGINE:
            return 3.0

        # Tool monologues are concrete progress updates and can follow thinking sooner.
        if event.source in {
            AvatarModule.DEEPRESEARCH,
            AvatarModule.MCP,
            AvatarModule.RAG,
        }:
            return 1.2

        return self.min_voice_interval_sec

    def _spoken_key(self, event: StatusEvent) -> tuple[Any, ...]:
        return (
            event.source,
            event.stage,
            event.type,
            self._semantic_key(event),
        )

    def _semantic_key(self, event: StatusEvent) -> str | None:
        query = event.metadata.get("query")
        if isinstance(query, str) and query.strip():
            return self._short_hash(query.strip())

        if event.message:
            return self._short_hash(event.message.strip())

        url_count = event.metadata.get("url_count")
        if url_count is not None:
            return f"url_count:{url_count}"

        op = event.metadata.get("op")
        if op is not None:
            return str(op)

        return None

    def _short_hash(self, text: str) -> str:
        return sha1(text.encode("utf-8")).hexdigest()[:12]

    async def _call_with_supported_kwargs(self, func, *args, **kwargs) -> None:
        sig = inspect.signature(func)
        supported_kwargs = {key: value for key, value in kwargs.items() if key in sig.parameters}

        result = func(*args, **supported_kwargs)
        if asyncio.iscoroutine(result):
            await result

    def _track_voice_task(self, task: asyncio.Task) -> None:
        self._voice_tasks.add(task)

        def _cleanup(t: asyncio.Task) -> None:
            self._voice_tasks.discard(t)

            try:
                exc = t.exception()
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.debug("Failed to inspect voice status task result: %s", e)
                return

            if exc is not None:
                logger.warning("Voice status task failed: %s", exc)

        task.add_done_callback(_cleanup)
