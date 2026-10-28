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

import hashlib
import pathlib
import re
from dataclasses import dataclass
from datetime import date

_SAFE_KEY = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?\Z")
_DEVICES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def path_key(value: str) -> str:
    """Map logical identifiers to portable keys without normalization or truncation."""
    if not isinstance(value, str) or not value or value != value.strip() or not value.isprintable():
        raise ValueError("An identifier must be nonempty printable text without outer whitespace")
    if _SAFE_KEY.fullmatch(value) and value.split(".", 1)[0] not in _DEVICES:
        return value
    # This prefix cannot occur in the unchanged key domain. Case and Unicode stay distinct.
    return "~id-" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def absolute_root(root: str | pathlib.Path) -> pathlib.Path:
    path = pathlib.Path(root)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("A filesystem root must be an explicit absolute path without '..'")
    return path


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
        user_key = path_key(user_id)
        root = self.root / user_key
        return UserPath(
            user_id=user_id,
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
        namespace = path_key(name)
        return GraphNamespacePath(name=namespace, root=self.root / namespace)


@dataclass(frozen=True, slots=True)
class MemoryExportPaths:
    root: pathlib.Path
    owners_dir: pathlib.Path
    episodes_dir: pathlib.Path
    contexts_dir: pathlib.Path

    def owner(self, kind: str, owner_id: str, memory_id: str) -> pathlib.Path:
        if kind not in {"avatar", "user"}:
            raise ValueError("Memory owner kind must be avatar or user")
        return self.owners_dir / kind / path_key(owner_id) / f"{path_key(memory_id)}.md"

    def episode(self, episode_id: str, memory_id: str) -> pathlib.Path:
        return self.episodes_dir / path_key(episode_id) / "memories" / f"{path_key(memory_id)}.md"

    def context(self, context_id: str, memory_id: str) -> pathlib.Path:
        return self.contexts_dir / path_key(context_id) / "memories" / f"{path_key(memory_id)}.md"


@dataclass(frozen=True, slots=True)
class MemoryPaths:
    root: pathlib.Path
    records_file: pathlib.Path
    exports: MemoryExportPaths


@dataclass(frozen=True, slots=True)
class EpisodePath:
    episode_id: str
    root: pathlib.Path

    @property
    def manifest_file(self) -> pathlib.Path:
        return self.root / "manifest.json"


@dataclass(frozen=True, slots=True)
class EpisodesPaths:
    root: pathlib.Path

    def get(self, episode_id: str) -> EpisodePath:
        eid = path_key(episode_id)
        return EpisodePath(episode_id=episode_id, root=self.root / eid)


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
        cid = path_key(context_id)
        root = self.root / cid
        return ContextPath(
            context_id=context_id,
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

    @property
    def manifest_file(self) -> pathlib.Path:
        return self.root / "manifest.json"


@dataclass(frozen=True, slots=True)
class SessionsPaths:
    root: pathlib.Path

    def get(self, session_id: str, created_date: date) -> SessionPath:
        sid = path_key(session_id)
        root = self.root / created_date.isoformat() / sid
        return SessionPath(
            session_id=session_id,
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
        backend = path_key(name)
        return IndexBackendPath(namespace=self.name, backend=backend, root=self.root / backend)


@dataclass(frozen=True, slots=True)
class IndexesPaths:
    root: pathlib.Path

    def namespace(self, name: str) -> IndexNamespacePath:
        namespace = path_key(name)
        return IndexNamespacePath(name=namespace, root=self.root / namespace)


@dataclass(frozen=True, slots=True)
class ArtifactsPaths:
    root: pathlib.Path

    def namespace(self, name: str) -> ArtifactNamespacePath:
        namespace = path_key(name)
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
        root = absolute_root(root)
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
