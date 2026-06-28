# Copyright 2025 AlphaAvatar project
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
import pathlib

from livekit.agents.llm import ChatItem, ChatMessage, FunctionCall, FunctionCallOutput

from alphaavatar.agents.utils import TimeStamp
from alphaavatar.agents.utils.files.work_dirs import SessionPath

from .enum.memory_type import MemoryType


def _normalize_object_ids(value: list[str] | str | None) -> list[str]:
    if value is None:
        return []

    values = value if isinstance(value, list) else [value]

    out: list[str] = []
    seen: set[str] = set()

    for x in values:
        s = str(x).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)

    return out


class MemoryCache:
    """Temporary memory cache for the current session."""

    def __init__(
        self,
        timestamp: TimeStamp,
        session_id: str,
        session_path: SessionPath,
        object_ids: list[str] | str | None,
        memory_type: MemoryType = MemoryType.CONVERSATION,
    ):
        self._timestamp = timestamp
        self._object_ids = _normalize_object_ids(object_ids)
        self._session_id = session_id
        self._session_path = session_path
        self._memory_type = memory_type
        self._messages: list[ChatItem] = []

    @property
    def time(self) -> str:
        return self._timestamp.time_str

    @property
    def object_ids(self) -> list[str]:
        return self._object_ids

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def provider_dir(self) -> pathlib.Path:
        return self._session_path.provider_dir

    @property
    def type(self) -> MemoryType:
        return self._memory_type

    @property
    def messages(self) -> list[ChatItem]:
        return self._messages

    @object_ids.setter
    def object_ids(self, value: list[str] | str | None) -> None:
        self._object_ids = _normalize_object_ids(value)

    def add_object_ids(self, value: list[str] | str | None) -> None:
        merged = self._object_ids + _normalize_object_ids(value)
        self._object_ids = _normalize_object_ids(merged)

    def add_message(self, message: ChatItem):
        """Add a new message to the cache."""
        if isinstance(message, ChatMessage) and message.role in ("user", "assistant"):
            self._messages.append(message)
        elif isinstance(message, FunctionCall) or isinstance(message, FunctionCallOutput):
            self._messages.append(message)

        self._messages.sort(key=lambda x: x.created_at)
