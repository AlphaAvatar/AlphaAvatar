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
import json

from livekit import rtc
from pydantic import BaseModel, ConfigDict, Field

from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.host.sessions.base import SessionConnection
from alphaavatar.host.sessions.schemas import SessionContext, SessionEnd, SessionRequest
from alphaavatar.rtc.livekit.utils.events import RoomEventBindings

from .config import LiveKitConfig, websocket_url


class LiveKitAccess(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    token: str = Field(min_length=1, repr=False)
    room_name: str = Field(min_length=1, max_length=256)
    agent_device_id: str = Field(min_length=1, max_length=256)
    device_id: str | None = Field(default=None, min_length=1, max_length=256)


class LiveKitConnection(SessionConnection):
    """Own one RTC connection and emit its end; never stop an Engine or delete a room."""

    def __init__(self, request: SessionRequest, config: LiveKitConfig) -> None:
        self.request, self._config = request, config
        self._access = LiveKitAccess.model_validate(request.connection)
        self.url = websocket_url(self._access.url)

        self.room = rtc.Room()
        self._events = RoomEventBindings(self.room)
        self._changed, self._ended = asyncio.Event(), asyncio.Event()
        self._end: SessionEnd | None = None
        self._context: SessionContext | None = None
        self._start_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._disconnect_task: asyncio.Task[None] | None = None

    @property
    def context(self) -> SessionContext:
        if self._context is None or self._end is not None:
            raise RuntimeError("LiveKit participant context is not available")
        return self._context

    def _signal_end(self, reason: str, *, failed: bool = False) -> None:
        if self._end is None:
            self._end = SessionEnd(self.request.attachment_id, reason, failed)
            self._ended.set()
            self._changed.set()

    def _candidate(self) -> rtc.RemoteParticipant | None:
        for participant in self.room.remote_participants.values():
            device_id = self._access.device_id
            if device_id is not None and participant.identity != device_id:
                continue
            if participant.kind in (
                rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD,
                rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
            ):
                return participant
        return None

    async def _start(self) -> None:
        @self._events.on("participant_connected")
        def participant_connected(_) -> None:
            if self._close_task is None:
                self._changed.set()

        @self._events.on("participant_disconnected")
        def participant_disconnected(participant: rtc.RemoteParticipant) -> None:
            if self._close_task is not None:
                return
            linked = self._context.device_id if self._context else self._access.device_id
            if linked is not None and participant.identity == linked:
                self._signal_end("linked_participant_disconnected")
            self._changed.set()

        @self._events.on("disconnected")
        def disconnected(*_) -> None:
            if self._close_task is None:
                self._signal_end("room_disconnected")

        async with asyncio.timeout(self._config.connect_timeout):
            await self.room.connect(
                self.url, self._access.token, options=rtc.RoomOptions(auto_subscribe=True)
            )

        self._access.token = ""
        if (
            self.room.name != self._access.room_name
            or self.room.local_participant.identity != self._access.agent_device_id
        ):
            raise RuntimeError("LiveKit room or participant identity did not match the assignment")

        async with asyncio.timeout(self._config.participant_timeout):
            while True:
                if self._end is not None or not self.room.isconnected():
                    raise RuntimeError("LiveKit connection ended before participant readiness")

                self._changed.clear()
                participant = self._candidate()
                if participant is not None:
                    if len(participant.metadata.encode("utf-8")) > 65536:
                        raise ValueError("Participant metadata is too large")

                    metadata = json.loads(participant.metadata) if participant.metadata else {}
                    if not isinstance(metadata, dict):
                        raise ValueError("Participant metadata must be a JSON object")

                    self._context = SessionContext(
                        device_id=participant.identity,
                        agent_device_id=self.room.local_participant.identity,
                        room_name=self.room.name,
                        metadata=metadata,
                    )
                    return
                await self._changed.wait()

    async def on_start(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("LiveKit connection is closing or closed")

        if self._start_task is None:
            self._start_task = asyncio.create_task(self._start(), name="livekit_connection_start")
            self._start_task.add_done_callback(
                lambda task: None if task.cancelled() else task.exception()
            )

        try:
            await asyncio.shield(self._start_task)
            if self._close_task is not None or self._end is not None:
                raise RuntimeError("LiveKit connection ended during startup")
        except BaseException as original:
            try:
                await self.on_stop()
            except BaseException as cleanup:
                raise original from cleanup
            raise

    async def wait_ended(self) -> SessionEnd:
        await self._ended.wait()
        assert self._end is not None
        return self._end

    async def _disconnect(self) -> None:
        async with asyncio.timeout(5.0):
            await self.room.disconnect()

    async def disconnect(self) -> None:
        if self._disconnect_task is None:
            self._disconnect_task = asyncio.create_task(
                self._disconnect(), name="livekit_room_disconnect"
            )
            self._disconnect_task.add_done_callback(
                lambda task: None if task.cancelled() else task.exception()
            )
        await wait_for_cleanup(self._disconnect_task)

    async def _close(self) -> None:
        self._signal_end("host_shutdown")
        errors: list[Exception] = []
        try:
            self._events.clear()
        except Exception as error:
            errors.append(error)

        if self._start_task is not None and not self._start_task.done():
            self._start_task.cancel()
            await asyncio.gather(self._start_task, return_exceptions=True)

        try:
            await self.disconnect()
        except Exception as error:
            errors.append(error)

        self._access.token = ""
        if errors:
            raise ExceptionGroup("LiveKit connection cleanup failed", errors)

    async def on_stop(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="livekit_connection_close")
            self._close_task.add_done_callback(
                lambda task: None if task.cancelled() else task.exception()
            )

        await wait_for_cleanup(self._close_task)
