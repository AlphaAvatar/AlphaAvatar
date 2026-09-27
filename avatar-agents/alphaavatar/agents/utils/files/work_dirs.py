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
import shutil
from dataclasses import dataclass
from datetime import date

from alphaavatar.agents.utils.id_utils import sanitize_id

from .op import _can_write_dir, _merge_dirs

AVATAR_WORK_DIR_ENV = "AVATAR_WORK_DIR"


def default_work_dir(app_name: str) -> pathlib.Path:
    preferred = pathlib.Path("/var/lib") / app_name
    if _can_write_dir(preferred):
        return preferred

    home = pathlib.Path.home()
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return pathlib.Path(xdg) / app_name
    return home / ".local" / "share" / app_name


def _namespace(value: str) -> str:
    value = str(value).strip()
    candidate = pathlib.Path(value)
    if not value or value in {".", ".."} or candidate.is_absolute() or len(candidate.parts) != 1:
        raise ValueError(f"Invalid workspace namespace: {value!r}")
    return sanitize_id(value)


@dataclass(frozen=True, slots=True)
class GraphNamespacePath:
    name: str
    root: pathlib.Path


@dataclass(frozen=True, slots=True)
class ArtifactNamespacePath:
    name: str
    root: pathlib.Path


@dataclass(frozen=True, slots=True)
class IndexBackendPath:
    namespace: str
    backend: str
    root: pathlib.Path


@dataclass(frozen=True, slots=True)
class UserPath:
    user_id: str
    root: pathlib.Path
    runtime_dir: pathlib.Path
    persona_dir: pathlib.Path
    identity_dir: pathlib.Path
    cache_dir: pathlib.Path
    logs_dir: pathlib.Path


@dataclass(frozen=True, slots=True)
class UsersPaths:
    root: pathlib.Path

    def get(self, user_id: str) -> UserPath:
        uid = sanitize_id(user_id)
        root = self.root / uid
        return UserPath(
            user_id=uid,
            root=root,
            runtime_dir=root / "runtime",
            persona_dir=root / "persona",
            identity_dir=root / "identity",
            cache_dir=root / ".cache",
            logs_dir=root / ".logs",
        )


@dataclass(frozen=True, slots=True)
class GraphPaths:
    root: pathlib.Path

    def namespace(self, name: str) -> GraphNamespacePath:
        namespace = _namespace(name)
        return GraphNamespacePath(name=namespace, root=self.root / namespace)


@dataclass(frozen=True, slots=True)
class MemoryExportPaths:
    root: pathlib.Path
    owners_dir: pathlib.Path
    episodes_dir: pathlib.Path
    contexts_dir: pathlib.Path


@dataclass(frozen=True, slots=True)
class MemoryPaths:
    root: pathlib.Path
    records_file: pathlib.Path
    exports: MemoryExportPaths


@dataclass(frozen=True, slots=True)
class EpisodePath:
    episode_id: str
    root: pathlib.Path


@dataclass(frozen=True, slots=True)
class EpisodesPaths:
    root: pathlib.Path

    def get(self, episode_id: str) -> EpisodePath:
        eid = sanitize_id(episode_id)
        return EpisodePath(episode_id=eid, root=self.root / eid)


@dataclass(frozen=True, slots=True)
class ContextPath:
    context_id: str
    root: pathlib.Path
    checkpoints_dir: pathlib.Path
    artifacts_dir: pathlib.Path


@dataclass(frozen=True, slots=True)
class ContextsPaths:
    root: pathlib.Path

    def get(self, context_id: str) -> ContextPath:
        cid = sanitize_id(context_id)
        root = self.root / cid
        return ContextPath(
            context_id=cid,
            root=root,
            checkpoints_dir=root / "checkpoints",
            artifacts_dir=root / "artifacts",
        )


@dataclass(frozen=True, slots=True)
class SessionPath:
    session_id: str
    created_date: date
    root: pathlib.Path
    provider_dir: pathlib.Path
    observations_dir: pathlib.Path
    turns_dir: pathlib.Path
    artifacts_dir: pathlib.Path
    logs_dir: pathlib.Path


@dataclass(frozen=True, slots=True)
class SessionsPaths:
    root: pathlib.Path

    def get(self, session_id: str, created_date: date) -> SessionPath:
        sid = sanitize_id(session_id)
        root = self.root / created_date.isoformat() / sid
        return SessionPath(
            session_id=sid,
            created_date=created_date,
            root=root,
            provider_dir=root / "provider",
            observations_dir=root / "observations",
            turns_dir=root / "turns",
            artifacts_dir=root / "artifacts",
            logs_dir=root / ".logs",
        )


@dataclass(frozen=True, slots=True)
class IndexNamespacePath:
    name: str
    root: pathlib.Path

    def backend(self, name: str) -> IndexBackendPath:
        backend = _namespace(name)
        return IndexBackendPath(
            namespace=self.name,
            backend=backend,
            root=self.root / backend,
        )


@dataclass(frozen=True, slots=True)
class IndexesPaths:
    root: pathlib.Path

    def namespace(self, name: str) -> IndexNamespacePath:
        namespace = _namespace(name)
        return IndexNamespacePath(name=namespace, root=self.root / namespace)


@dataclass(frozen=True, slots=True)
class ArtifactsPaths:
    root: pathlib.Path

    def namespace(self, name: str) -> ArtifactNamespacePath:
        namespace = _namespace(name)
        return ArtifactNamespacePath(name=namespace, root=self.root / namespace)


@dataclass(frozen=True, slots=True)
class DataPaths:
    root: pathlib.Path
    memory: MemoryPaths
    episodes: EpisodesPaths
    contexts: ContextsPaths
    sessions: SessionsPaths
    indexes: IndexesPaths
    artifacts: ArtifactsPaths


@dataclass(frozen=True, slots=True)
class WorkspacePaths:
    root: pathlib.Path
    env_dir: pathlib.Path
    users: UsersPaths
    graph: GraphPaths
    data: DataPaths
    logs_dir: pathlib.Path
    cache_dir: pathlib.Path

    @classmethod
    def from_root(cls, root: str | pathlib.Path) -> WorkspacePaths:
        root = pathlib.Path(root).expanduser()
        data_root = root / "data"
        memory_root = data_root / "memory"
        exports_root = memory_root / "exports"

        return cls(
            root=root,
            env_dir=root / "env",
            users=UsersPaths(root / "users"),
            graph=GraphPaths(root / "graph"),
            data=DataPaths(
                root=data_root,
                memory=MemoryPaths(
                    root=memory_root,
                    records_file=memory_root / "records.sqlite3",
                    exports=MemoryExportPaths(
                        root=exports_root,
                        owners_dir=exports_root / "owners",
                        episodes_dir=exports_root / "episodes",
                        contexts_dir=exports_root / "contexts",
                    ),
                ),
                episodes=EpisodesPaths(data_root / "episodes"),
                contexts=ContextsPaths(data_root / "contexts"),
                sessions=SessionsPaths(data_root / "sessions"),
                indexes=IndexesPaths(data_root / "indexes"),
                artifacts=ArtifactsPaths(data_root / "artifacts"),
            ),
            logs_dir=root / ".logs",
            cache_dir=root / ".cache",
        )

    @classmethod
    def from_env(cls) -> WorkspacePaths:
        root = os.getenv(AVATAR_WORK_DIR_ENV, "").strip()
        if not root:
            raise RuntimeError(f"{AVATAR_WORK_DIR_ENV} is not configured")
        return cls.from_root(root)


def prepare_workspace(paths: WorkspacePaths) -> None:
    for directory in (
        paths.root,
        paths.env_dir,
        paths.users.root,
        paths.graph.root,
        paths.data.root,
        paths.data.memory.root,
        paths.data.memory.exports.root,
        paths.data.memory.exports.owners_dir,
        paths.data.memory.exports.episodes_dir,
        paths.data.memory.exports.contexts_dir,
        paths.data.episodes.root,
        paths.data.contexts.root,
        paths.data.sessions.root,
        paths.data.indexes.root,
        paths.data.artifacts.root,
        paths.logs_dir,
        paths.cache_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def prepare_session_path(path: SessionPath) -> None:
    for directory in (
        path.root,
        path.provider_dir,
        path.observations_dir,
        path.turns_dir,
        path.artifacts_dir,
        path.logs_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def prepare_user_path(path: UserPath) -> None:
    for directory in (
        path.root,
        path.runtime_dir,
        path.persona_dir,
        path.identity_dir,
        path.cache_dir,
        path.logs_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def migrate_user_path(
    *,
    old_user_path: UserPath,
    new_user_path: UserPath,
    remove_old: bool = False,
) -> None:
    if old_user_path.root.resolve() == new_user_path.root.resolve():
        return

    prepare_user_path(new_user_path)

    _merge_dirs(old_user_path.runtime_dir, new_user_path.runtime_dir)
    _merge_dirs(old_user_path.persona_dir, new_user_path.persona_dir)
    _merge_dirs(old_user_path.identity_dir, new_user_path.identity_dir)
    _merge_dirs(old_user_path.cache_dir, new_user_path.cache_dir)
    _merge_dirs(old_user_path.logs_dir, new_user_path.logs_dir)

    if remove_old:
        shutil.rmtree(old_user_path.root, ignore_errors=True)
