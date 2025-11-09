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
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .enum.op import OpType

if TYPE_CHECKING:
    from ..engine import AvatarEngine
    from . import ObservableList


class ContextManager:
    def __init__(self, engine: AvatarEngine):
        self._engine = engine

    def memory_context_watcher(
        self, chat_context: ObservableList, op: OpType, payload: dict[str, Any]
    ):
        if op == OpType.INSERT:
            self._engine.memory.add_message(
                session_id=self._engine.session_config.session_id, chat_item=payload["value"]
            )

    def persona_context_watcher(
        self, chat_context: ObservableList, op: OpType, payload: dict[str, Any]
    ):
        if op == OpType.INSERT:
            self._engine.persona.add_message(
                user_id=self._engine.session_config.user_id, chat_item=payload["value"]
            )

    def __call__(self, chat_context: ObservableList, op: OpType, payload: dict[str, Any]):
        # Fix init config when user info update
        if self._engine.session_config.user_id != self._engine.persona.default_uid:
            self._engine.memory.update_user_tool_id(
                ori_id=self._engine.session_config.user_id,
                tgt_id=self._engine.persona.default_uid,
            )
            self._engine.session_config.user_id = self._engine.persona.default_uid

        # Notify memory
        self.memory_context_watcher(chat_context=chat_context, op=op, payload=payload)

        # Notify persona
        self.persona_context_watcher(chat_context=chat_context, op=op, payload=payload)
