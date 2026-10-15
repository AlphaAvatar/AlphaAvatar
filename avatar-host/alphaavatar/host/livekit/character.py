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
import os
from collections.abc import Callable
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import uuid4

from livekit import api, rtc

from alphaavatar.agents.character import CharacterConnection, CharacterTransport


class LiveKitCharacterTransport(CharacterTransport):
    """Authenticate renderer readiness in one room; never own media generation or the room."""

    def __init__(
        self,
        *,
        room: rtc.Room,
        agent_identity: str,
        livekit_url: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
    ) -> None:
        self._room, self._agent_identity = room, agent_identity
        self._url = livekit_url if livekit_url is not None else os.getenv("LIVEKIT_URL", "")
        self._api_key = api_key if api_key is not None else os.getenv("LIVEKIT_API_KEY", "")
        self._api_secret = (
            api_secret if api_secret is not None else os.getenv("LIVEKIT_API_SECRET", "")
        )
        parsed = urlsplit(self._url)

        if (
            parsed.scheme not in ("ws", "wss", "http", "https")
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or any(c.isspace() for c in self._url)
        ):
            raise ValueError("Character requires a LiveKit URL without credentials or query")

        try:
            _ = parsed.port
        except ValueError:
            raise ValueError("Character LiveKit URL has an invalid port") from None

        if parsed.scheme in ("http", "ws") and parsed.hostname not in (
            "localhost",
            "127.0.0.1",
            "::1",
        ):
            raise ValueError("Remote Character connections require TLS")
        if not all(
            isinstance(v, str) and v.strip()
            for v in (agent_identity, self._api_key, self._api_secret)
        ):
            raise ValueError("Character requires Agent identity and LiveKit service credentials")

        self._identity = f"alphaavatar-character-{uuid4().hex}"
        self._connection: CharacterConnection | None = None
        self._callbacks: list[tuple[str, Callable]] = []
        self._changed, self._failed = asyncio.Event(), asyncio.Event()
        self._failure: RuntimeError | None = None
        self._ready_seen = self._started = self._closed = False

    @property
    def participant_identity(self) -> str:
        return self._identity

    @property
    def connection(self) -> CharacterConnection:
        if self._connection is None or self._closed:
            raise RuntimeError("Character transport is not open")
        return self._connection

    def _fail(self, reason: str) -> None:
        if not self._closed and self._failure is None:
            self._failure = RuntimeError(reason)
            self._failed.set()
            self._changed.set()

    def _on_data(self, packet: rtc.DataPacket) -> None:
        if (
            self._closed
            or not self._started
            or packet.topic != "avatar_status"
            or packet.participant is None
            or packet.participant.identity != self._identity
            or len(packet.data) > 1024
        ):
            return

        try:
            message = json.loads(packet.data)
        except (ValueError, UnicodeError, TypeError):
            return

        if isinstance(message, dict) and message.get("type") == "avatar_ready":
            self._ready_seen = True
            self._changed.set()

    def _on_track(
        self, publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant
    ) -> None:
        if participant.identity != self._identity or self._closed:
            return
        if publication.kind == rtc.TrackKind.KIND_AUDIO:
            self._fail("Character attempted to publish a second audio track")
        self._changed.set()

    def _on_unpublished(
        self, publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant
    ) -> None:
        if participant.identity == self._identity and publication.kind == rtc.TrackKind.KIND_VIDEO:
            self._fail("Character video publication ended unexpectedly")

    def _on_participant(self, participant: rtc.RemoteParticipant) -> None:
        if participant.identity == self._identity:
            self._changed.set()

    def _on_participant_left(self, participant: rtc.RemoteParticipant) -> None:
        if participant.identity == self._identity:
            self._fail("Character participant disconnected unexpectedly")

    def _on_disconnected(self, *_) -> None:
        self._fail("Character room disconnected")

    def _has_video(self) -> bool:
        participant = self._room.remote_participants.get(self._identity)
        if participant is None:
            return False

        publications = tuple(participant.track_publications.values())
        if any(p.kind == rtc.TrackKind.KIND_AUDIO for p in publications):
            self._fail("Character attempted to publish a second audio track")
            return False

        return any(p.kind == rtc.TrackKind.KIND_VIDEO for p in publications)

    async def on_start(self) -> None:
        if self._closed:
            raise RuntimeError("Character transport is closed")
        if self._started:
            return
        if not self._room.isconnected():
            raise RuntimeError("Character requires a connected room")

        # Register before launching the renderer; a fast READY cannot be lost.
        for event, callback in (
            ("data_received", self._on_data),
            ("track_published", self._on_track),
            ("track_unpublished", self._on_unpublished),
            ("participant_connected", self._on_participant),
            ("participant_disconnected", self._on_participant_left),
            ("disconnected", self._on_disconnected),
        ):
            self._room.on(event, callback)
            self._callbacks.append((event, callback))

        token = (
            api.AccessToken(self._api_key, self._api_secret)
            .with_kind("agent")
            .with_identity(self._identity)
            .with_ttl(timedelta(minutes=5))
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=self._room.name,
                    can_publish=True,
                    can_subscribe=True,
                    can_publish_data=True,
                    can_update_own_metadata=False,
                )
            )
            .with_attributes({"lk.publish_on_behalf": self._agent_identity})
            .to_jwt()
        )

        self._connection = CharacterConnection(
            transport="livekit",
            url=self._url,
            agent_identity=self._agent_identity,
            participant_identity=self._identity,
            token=token,
        )
        self._api_key = self._api_secret = ""
        self._started = True

    async def wait_ready(self) -> None:
        while True:
            if self._closed or not self._started:
                raise RuntimeError("Character transport is not open")
            if self._failure is not None:
                raise self._failure
            if self._ready_seen and self._has_video():
                return
            if self._failure is not None:
                raise self._failure
            self._changed.clear()
            await self._changed.wait()

    async def wait_failed(self) -> None:
        await self._failed.wait()
        raise RuntimeError("Character transport failed") from self._failure

    async def on_stop(self) -> None:
        if self._closed:
            return

        self._closed = True
        self._connection = None
        self._api_key = self._api_secret = ""
        errors: list[Exception] = []
        for event, callback in self._callbacks:
            try:
                self._room.off(event, callback)
            except Exception:
                errors.append(RuntimeError(f"Character callback removal failed: {event}"))

        self._callbacks.clear()
        self._changed.set()
        if errors:
            raise ExceptionGroup("Character transport cleanup failed", errors)
