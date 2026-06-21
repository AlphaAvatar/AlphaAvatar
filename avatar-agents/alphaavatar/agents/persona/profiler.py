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

import json
import pathlib
import re
from abc import abstractmethod
from typing import TYPE_CHECKING

from alphaavatar.agents.log import logger
from alphaavatar.agents.runtime.session_runtime import SessionRuntime
from alphaavatar.agents.utils.files.user_dirs import UserPath, mk_user_dirs
from alphaavatar.agents.utils.files.work_dirs import AvatarPath

from .schema.user_profile import UserProfile, UserRuntimeState

if TYPE_CHECKING:
    from .cache import PersonaCache


_RUNTIME_JSON_BEGIN = "<!-- alphaavatar_runtime_state_json:start -->"
_RUNTIME_JSON_END = "<!-- alphaavatar_runtime_state_json:end -->"


class ProfilerBase:
    def __init__(self): ...

    def _get_runtime_path_for_user(self, uid: str, work_dir: AvatarPath) -> pathlib.Path:
        user_path: UserPath = mk_user_dirs(work_dir.users_dir, uid)
        path = user_path.runtime_dir
        path = path / "runtime_state.md"
        return path

    async def load_runtime_state(
        self, *, uid: str, work_dir: AvatarPath
    ) -> UserRuntimeState | None:
        path = self._get_runtime_path_for_user(uid, work_dir)
        if not path.exists():
            return None

        text = path.read_text(encoding="utf-8")

        pattern = (
            re.escape(_RUNTIME_JSON_BEGIN)
            + r"\s*```json\s*(.*?)\s*```\s*"
            + re.escape(_RUNTIME_JSON_END)
        )

        match = re.search(pattern, text, flags=re.DOTALL)
        if not match:
            return None

        try:
            data = json.loads(match.group(1))
            return UserRuntimeState(**data)
        except Exception as e:
            logger.warning(f"Runtime state load failed: {e}")
            return None

    async def save_runtime_state(
        self,
        *,
        uid: str,
        runtime_state: UserRuntimeState,
        work_dir: AvatarPath,
    ) -> pathlib.Path:
        path = self._get_runtime_path_for_user(uid=uid, work_dir=work_dir)

        state_data = runtime_state.model_dump(mode="json", exclude_none=True)

        session_id = runtime_state.current_session_id or ""
        login_time = runtime_state.current_login_time or ""
        timezone = runtime_state.current_timezone or ""
        room_type = runtime_state.current_room_type or ""
        login_count = str(runtime_state.login_count or 0)

        latest_block = (
            f"{_RUNTIME_JSON_BEGIN}\n"
            "```json\n"
            f"{json.dumps(state_data, ensure_ascii=False, indent=2)}\n"
            "```\n"
            f"{_RUNTIME_JSON_END}"
        )

        history_item = (
            f"<!-- session_id:{session_id or ''} -->\n"
            f"- login_time: {login_time}\n"
            f"  session_id: {session_id or ''}\n"
            f"  room_type: {room_type}\n"
            f"  timezone: {timezone}\n"
            f"  login_count: {login_count}\n"
        )

        if path.exists():
            old_text = path.read_text(encoding="utf-8")

            pattern = re.escape(_RUNTIME_JSON_BEGIN) + r".*?" + re.escape(_RUNTIME_JSON_END)

            if re.search(pattern, old_text, flags=re.DOTALL):
                new_text = re.sub(pattern, latest_block, old_text, flags=re.DOTALL)
            else:
                new_text = f"# Runtime State\n\n{latest_block}\n\n## Previous Content\n\n{old_text}"

            if "## Login History" not in new_text:
                new_text = new_text.rstrip() + "\n\n## Login History\n\n"

            session_marker = f"<!-- session_id:{session_id} -->"
            if session_id and session_marker not in new_text:
                new_text = new_text.rstrip() + "\n\n" + history_item
        else:
            new_text = f"# Runtime State\n\n{latest_block}\n\n## Login History\n\n{history_item}"

        path.write_text(new_text, encoding="utf-8")
        return path

    @abstractmethod
    async def load(self, *, uid: str, work_dir: AvatarPath) -> UserProfile: ...

    @abstractmethod
    async def search(self, *, profile: UserProfile): ...

    @abstractmethod
    async def update(self, *, uid: str, persona: PersonaCache, session_runtime: SessionRuntime): ...

    @abstractmethod
    async def save(self, *, uid: str, persona: PersonaCache, work_dir: AvatarPath) -> None: ...
