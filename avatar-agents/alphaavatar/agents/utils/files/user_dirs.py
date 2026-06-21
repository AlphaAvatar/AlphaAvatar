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

import pathlib
import shutil
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from alphaavatar.agents.utils.id_utils import sanitize_id

from .op import _merge_dirs


class UserPathSnapshot(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: str
    user_root: pathlib.Path
    runtime_dir: pathlib.Path
    persona_dir: pathlib.Path
    identity_dir: pathlib.Path
    cache_dir: pathlib.Path
    logs_dir: pathlib.Path


UserPathChangeCallback = Callable[
    ["UserPath", UserPathSnapshot, UserPathSnapshot],
    Any,
]


class UserPath(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: str = Field(..., description="Sanitized user id used in folder names.")
    user_root: pathlib.Path

    runtime_dir: pathlib.Path
    persona_dir: pathlib.Path
    identity_dir: pathlib.Path
    cache_dir: pathlib.Path
    logs_dir: pathlib.Path

    _callbacks: list[UserPathChangeCallback] = PrivateAttr(default_factory=list)
    _version: int = PrivateAttr(default=0)

    @property
    def version(self) -> int:
        return self._version

    def snapshot(self) -> UserPathSnapshot:
        return UserPathSnapshot(
            user_id=self.user_id,
            user_root=self.user_root,
            runtime_dir=self.runtime_dir,
            persona_dir=self.persona_dir,
            identity_dir=self.identity_dir,
            cache_dir=self.cache_dir,
            logs_dir=self.logs_dir,
        )

    def subscribe(self, callback: UserPathChangeCallback):
        self._callbacks.append(callback)

        def unsubscribe():
            try:
                self._callbacks.remove(callback)
            except ValueError:
                pass

        return unsubscribe

    def update_from(self, new_path: UserPath) -> None:
        old = self.snapshot()

        self.user_id = new_path.user_id
        self.user_root = new_path.user_root
        self.runtime_dir = new_path.runtime_dir
        self.persona_dir = new_path.persona_dir
        self.identity_dir = new_path.identity_dir
        self.cache_dir = new_path.cache_dir
        self.logs_dir = new_path.logs_dir
        self._version += 1

        new = self.snapshot()

        for callback in list(self._callbacks):
            callback(self, old, new)


def mk_user_dirs(users_dir: str | pathlib.Path, user_id: str) -> UserPath:
    base = pathlib.Path(users_dir)
    uid = sanitize_id(user_id)

    user_root = base / uid
    runtime_dir = user_root / "runtime"
    persona_dir = user_root / "persona"
    identity_dir = user_root / "identity"
    cache_dir = user_root / ".cache"
    logs_dir = user_root / ".logs"

    for d in [runtime_dir, persona_dir, identity_dir, cache_dir, logs_dir]:
        d.mkdir(parents=True, exist_ok=True)

    return UserPath(
        user_id=uid,
        user_root=user_root,
        runtime_dir=runtime_dir,
        persona_dir=persona_dir,
        identity_dir=identity_dir,
        cache_dir=cache_dir,
        logs_dir=logs_dir,
    )


def migrate_user_path(
    *,
    old_user_path: UserPath | UserPathSnapshot,
    new_user_path: UserPath | UserPathSnapshot,
    remove_old: bool = False,
) -> None:
    if old_user_path.user_root.resolve() == new_user_path.user_root.resolve():
        return

    _merge_dirs(old_user_path.runtime_dir, new_user_path.runtime_dir)
    _merge_dirs(old_user_path.persona_dir, new_user_path.persona_dir)
    _merge_dirs(old_user_path.identity_dir, new_user_path.identity_dir)
    _merge_dirs(old_user_path.cache_dir, new_user_path.cache_dir)
    _merge_dirs(old_user_path.logs_dir, new_user_path.logs_dir)

    if remove_old:
        shutil.rmtree(old_user_path.user_root, ignore_errors=True)
