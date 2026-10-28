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

from dataclasses import dataclass
from pathlib import Path

from .paths import WorkspacePaths, absolute_root, path_key


@dataclass(frozen=True, slots=True)
class ConfigPaths:
    root: Path
    profiles_dir: Path
    bundles_dir: Path


@dataclass(frozen=True, slots=True)
class CachePaths:
    root: Path
    models_dir: Path
    downloads_dir: Path
    providers_dir: Path
    diagnostics_dir: Path
    avatars_dir: Path

    def avatar(self, avatar_id: str) -> Path:
        return self.avatars_dir / path_key(avatar_id)


@dataclass(frozen=True, slots=True)
class ApplicationPaths:
    root: Path
    configs: ConfigPaths
    settings_dir: Path
    settings_file: Path
    cache: CachePaths
    avatars_dir: Path

    @classmethod
    def from_root(
        cls, root: str | Path, *, cache_root: str | Path | None = None
    ) -> ApplicationPaths:
        root = absolute_root(root)
        cache = absolute_root(cache_root) if cache_root is not None else root / "cache"
        configs = root / "configs"
        settings = root / "settings"
        return cls(
            root=root,
            configs=ConfigPaths(configs, configs / "profiles", configs / "bundles"),
            settings_dir=settings,
            settings_file=settings / "settings.yaml",
            cache=CachePaths(
                cache,
                cache / "models",
                cache / "downloads",
                cache / "providers",
                cache / "diagnostics",
                cache / "avatars",
            ),
            avatars_dir=root / "avatars",
        )

    def workspace(self, avatar_id: str) -> WorkspacePaths:
        return WorkspacePaths.from_root(self.avatars_dir / path_key(avatar_id))
