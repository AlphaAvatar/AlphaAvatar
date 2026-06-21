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

import os
import pathlib

from pydantic import BaseModel, ConfigDict, Field

from alphaavatar.agents.utils.id_utils import sanitize_id

from .op import _can_write_dir


def default_work_dir(app_name: str) -> pathlib.Path:
    # Preferred server path
    preferred = pathlib.Path("/var/lib") / app_name
    if _can_write_dir(preferred):
        return preferred

    # Fallback for non-root user
    home = pathlib.Path.home()
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return pathlib.Path(xdg) / app_name
    return home / ".local" / "share" / app_name


class AvatarPath(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    work_dir: pathlib.Path = Field(...)

    # work_dir
    data_dir: pathlib.Path
    users_dir: pathlib.Path
    env_dir: pathlib.Path

    # /data_dir
    sessions_dir: pathlib.Path
    memory_dir: pathlib.Path
    graph_dir: pathlib.Path
    artifacts_dir: pathlib.Path

    logs_dir: pathlib.Path
    cache_dir: pathlib.Path

    def session_dir(self, session_id: str) -> pathlib.Path:
        path = self.sessions_dir / sanitize_id(session_id)
        path.mkdir(parents=True, exist_ok=True)
        return path


class SessionPath(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: str
    session_root: pathlib.Path

    provider_dir: pathlib.Path
    memory_dir: pathlib.Path
    observations_dir: pathlib.Path
    turns_dir: pathlib.Path
    artifacts_dir: pathlib.Path
    logs_dir: pathlib.Path


def mk_avatar_dirs(work_dir: str | pathlib.Path) -> AvatarPath:
    base = pathlib.Path(work_dir)

    data_dir = base / "data"
    users_dir = base / "users"
    env_dir = base / "env"

    sessions_dir = data_dir / "sessions"
    memory_dir = data_dir / "memory"
    graph_dir = data_dir / "graph"
    artifacts_dir = data_dir / "artifacts"

    logs_dir = base / ".logs"
    cache_dir = base / ".cache"

    for d in [
        data_dir,
        users_dir,
        env_dir,
        sessions_dir,
        memory_dir,
        graph_dir,
        artifacts_dir,
        logs_dir,
        cache_dir,
    ]:
        d.mkdir(parents=True, exist_ok=True)

    return AvatarPath(
        work_dir=base,
        data_dir=data_dir,
        users_dir=users_dir,
        env_dir=env_dir,
        sessions_dir=sessions_dir,
        memory_dir=memory_dir,
        graph_dir=graph_dir,
        artifacts_dir=artifacts_dir,
        logs_dir=logs_dir,
        cache_dir=cache_dir,
    )


def mk_session_dirs(avatar_path: AvatarPath, session_id: str) -> SessionPath:
    sid = sanitize_id(session_id)
    session_root = avatar_path.sessions_dir / sid

    provider_dir = session_root / "provider"
    memory_dir = session_root / "memory"
    observations_dir = session_root / "observations"
    turns_dir = session_root / "turns"
    artifacts_dir = session_root / "artifacts"
    logs_dir = session_root / ".logs"

    for d in [
        session_root,
        provider_dir,
        memory_dir,
        observations_dir,
        turns_dir,
        artifacts_dir,
        logs_dir,
    ]:
        d.mkdir(parents=True, exist_ok=True)

    return SessionPath(
        session_id=sid,
        session_root=session_root,
        provider_dir=provider_dir,
        memory_dir=memory_dir,
        observations_dir=observations_dir,
        turns_dir=turns_dir,
        artifacts_dir=artifacts_dir,
        logs_dir=logs_dir,
    )
