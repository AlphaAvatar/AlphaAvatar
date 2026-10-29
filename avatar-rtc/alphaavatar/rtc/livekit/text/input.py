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
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from math import isfinite

from livekit import rtc

from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.env.enums import ObservationKind
from alphaavatar.core.env.schemas import PerceptionSourceRef
from alphaavatar.core.lifecycle import LifecycleComponent
from alphaavatar.core.media import TextPayload
from alphaavatar.core.time import RuntimeClock, RuntimeTimeRange

logger = logging.getLogger(__name__)


class LiveKitTextInput(LifecycleComponent):
    """Accept complete authenticated lk.chat streams without an AgentSession.

    RTC readers in the supported SDK have no public abort API. Read failures are
    fatal to this connection: the Host must observe wait_failed(), disconnect the
    room, then retire this adapter. Never keep an abandoned stream on a live room.
    """

    TOPIC = "lk.chat"

    def __init__(
        self,
        *,
        room: rtc.Room,
        clock: RuntimeClock,
        session_id: str,
        device_ids: frozenset[str],
        submit: Callable[[EnvObservation], Awaitable[None]],
        max_streams: int = 16,
        max_bytes: int = 262144,
        read_timeout: float = 15.0,
    ) -> None:
        if (
            not session_id
            or not device_ids
            or any(not isinstance(v, str) or not v for v in device_ids)
        ):
            raise ValueError("Text input requires a session and authorized transport IDs")
        if (
            type(max_streams) is not int
            or max_streams < 1
            or type(max_bytes) is not int
            or max_bytes < 1
        ):
            raise ValueError("Text input capacities must be positive integers")
        if not isfinite(read_timeout) or read_timeout <= 0 or not callable(submit):
            raise ValueError("Text input requires a positive timeout and submit callback")
        self._room, self._clock, self._session_id = room, clock, session_id
        self._device_ids, self._submit = frozenset(device_ids), submit
        self._max_streams, self._max_bytes, self._timeout = max_streams, max_bytes, read_timeout
        self._tasks: set[asyncio.Task[None]] = set()
        self._failure: Exception | None = None
        self._failed = asyncio.Event()
        self._registered = False
        self._close_task: asyncio.Task[None] | None = None

    @property
    def has_pending_streams(self) -> bool:
        return bool(self._tasks)

    def _fail(self, error: BaseException) -> None:
        if isinstance(error, asyncio.CancelledError):
            failure = RuntimeError("Text reader cancelled before owner shutdown")
            failure.__cause__ = error
        elif isinstance(error, Exception):
            failure = error
        else:
            raise error
        if self._failure is None:
            self._failure = failure
            self._failed.set()
            logger.error("Native text input failed; connection must close", exc_info=failure)

    def _observe(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            if self._close_task is None:
                self._fail(asyncio.CancelledError())
        elif (error := task.exception()) is not None:
            self._fail(error)

    def _receive(self, reader: rtc.TextStreamReader, device_id: str) -> None:
        # Identity comes from the RTC callback, never from reader attributes.
        if self._close_task is not None or self._failure is not None:
            self._fail(RuntimeError("Text stream arrived after intake closed"))
            return
        if device_id not in self._device_ids:
            self._fail(PermissionError("Text sender is not attached to this Avatar session"))
            return
        if len(self._tasks) >= self._max_streams:
            self._fail(RuntimeError("Text stream capacity exhausted"))
            return
        task = asyncio.create_task(self._read(reader, device_id), name="livekit_text_input")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(self._observe)

    async def _read(self, reader: rtc.TextStreamReader, device_id: str) -> None:
        info = reader.info
        if not isinstance(info.stream_id, str) or not 1 <= len(info.stream_id) <= 512:
            raise ValueError("Invalid RTC text stream identity")
        if info.attachments:
            raise ValueError("Attached byte streams are not supported by the text-only ingress")
        if info.size is not None and (
            type(info.size) is not int or not 0 <= info.size <= self._max_bytes
        ):
            raise ValueError("Text header exceeds its byte capacity")
        chunks, size = [], 0
        async with asyncio.timeout(self._timeout):
            async for chunk in reader:
                if not isinstance(chunk, str):
                    raise TypeError("RTC text streams must contain strings")
                size += len(chunk.encode("utf-8"))
                if size > self._max_bytes:
                    raise ValueError("Text stream exceeds its byte capacity")
                chunks.append(chunk)
        if info.size and size != info.size:
            raise ValueError("Text stream ended before its declared byte length")
        text = "".join(chunks)
        if not text.strip():
            return
        key = json.dumps([self._session_id, device_id, info.stream_id], ensure_ascii=False).encode()
        observation = EnvObservation(
            observation_id=f"rtc_text:{hashlib.sha256(key).hexdigest()}",
            kind=ObservationKind.TEXT_INPUT,
            time_range=RuntimeTimeRange.point(self._clock.now()),
            source=PerceptionSourceRef(source_id=f"env:text:{device_id}", source_generation=1),
            device_id=device_id,
            payload=TextPayload.create(text=text),
            mime_type="text/plain",
            metadata={"rtc_backend": "livekit"},
        )
        # Engine owns atomic perception publication + committed Turn creation.
        await self._submit(observation)

    async def wait_failed(self) -> None:
        await self._failed.wait()
        raise RuntimeError("Native RTC text input failed") from self._failure

    async def on_start(self) -> None:
        if self._close_task is not None or self._failure is not None:
            raise RuntimeError("Text input is closing or failed")
        if not self._registered:
            self._room.register_text_stream_handler(self.TOPIC, self._receive)
            self._registered = True

    async def _close(self) -> None:
        errors: list[Exception] = []
        if self._registered:
            try:
                self._room.unregister_text_stream_handler(self.TOPIC)
            except Exception as error:
                errors.append(error)
            self._registered = False
        pending = tuple(self._tasks)
        for task in pending:
            if not task.done() and not task.cancelling():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in pending:
            self._observe(task)
        if self._failure is not None:
            errors.append(self._failure)
        if errors:
            raise ExceptionGroup("RTC text input shutdown failed", errors)

    async def on_stop(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="livekit_text_close")
        await wait_for_cleanup(self._close_task)
