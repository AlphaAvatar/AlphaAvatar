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

from collections.abc import Iterable
from pathlib import Path

from alphaavatar.agents.workspace import WorkspaceMigrationRequired, WorkspacePaths

from .application import ApplicationPaths


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
