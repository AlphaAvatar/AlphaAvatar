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

from collections.abc import Callable
from typing import TypeVar

from livekit import rtc
from livekit.rtc.room import EventTypes

Callback = TypeVar("Callback", bound=Callable[..., None])


class RoomEventBindings:
    """Own only the room callbacks registered by one adapter."""

    def __init__(self, room: rtc.Room) -> None:
        self._room = room
        self._callbacks: list[tuple[EventTypes, Callable[..., None]]] = []

    @property
    def registered(self) -> bool:
        return bool(self._callbacks)

    def on(self, event: EventTypes) -> Callable[[Callback], Callback]:
        def register(callback: Callback) -> Callback:
            self._room.on(event, callback)
            self._callbacks.append((event, callback))
            return callback

        return register

    def clear(self) -> None:
        for event, callback in self._callbacks:
            self._room.off(event, callback)
        self._callbacks.clear()
