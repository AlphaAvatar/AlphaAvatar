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
import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path

from .application import ApplicationPaths
from .paths import SessionPath, UserPath, WorkspacePaths, path_key


class WorkspaceMigrationRequired(ValueError):
    """Existing identity data requires an explicit, reversible migration."""


def check_legacy_identity(parent: Path, identity: str) -> None:
    key = path_key(identity)
    legacy = re.sub(r"[^a-zA-Z0-9._-]+", "_", identity).strip("._-")[:64] or "unknown"
    candidates = {legacy}
    if identity not in {".", ".."} and not any(c in identity for c in "/\\\x00"):
        candidates.add(identity)

    def alias(name: str) -> str:
        return unicodedata.normalize("NFC", unicodedata.normalize("NFC", name).casefold())

    aliases = {alias(candidate) for candidate in candidates | {key}}
    try:
        entries = os.scandir(parent)
    except FileNotFoundError:
        return
    # Inspect actual names: exists("alice") can already resolve an old "Alice" directory
    # on a case-insensitive filesystem. Do not stat or traverse each user's contents.
    with entries:
        for entry in entries:
            if entry.name != key and alias(entry.name) in aliases:
                raise WorkspaceMigrationRequired(
                    f"Existing identity data at {parent / entry.name} cannot be silently rebound. "
                    "Back it up and explicitly migrate its identity references before continuing."
                )


def check_workspace_continuity(paths: WorkspacePaths, previous_roots: Iterable[Path]) -> None:
    """Refuse to silently replace an existing default workspace with an empty one."""
    for previous in previous_roots:
        if previous.resolve() == paths.root.resolve():
            continue
        if any((previous / name).exists() for name in ("users", "data", "graph")):
            raise WorkspaceMigrationRequired(
                f"Existing workspace data was found at {previous}. Set avatar.workspace_root "
                "to that complete directory, or explicitly back up and relocate it before "
                "starting with a new workspace. No existing data has been moved or deleted."
            )


def prepare_application(paths: ApplicationPaths) -> None:
    for directory in (
        paths.root,
        paths.configs.root,
        paths.configs.profiles_dir,
        paths.configs.bundles_dir,
        paths.settings_dir,
        paths.cache.root,
        paths.cache.models_dir,
        paths.cache.downloads_dir,
        paths.cache.providers_dir,
        paths.cache.diagnostics_dir,
        paths.cache.avatars_dir,
        paths.avatars_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)


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


def prepare_user_path(path: UserPath) -> None:
    check_legacy_identity(path.root.parent, path.user_id)
    for directory in (
        path.root,
        path.runtime_dir,
        path.persona_dir,
        path.identity_dir,
        path.cache_dir,
        path.logs_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def prepare_session_path(path: SessionPath) -> None:
    check_legacy_identity(path.root.parent, path.session_id)
    for directory in (
        path.root,
        path.provider_dir,
        path.observations_dir,
        path.turns_dir,
        path.artifacts_dir,
        path.logs_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
