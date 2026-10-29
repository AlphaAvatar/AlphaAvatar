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

import sys
from collections.abc import Mapping
from pathlib import Path

from alphaavatar.core.workspace import ApplicationPaths


def resolve_application_paths(
    environ: Mapping[str, str], *, default_root: str | Path
) -> ApplicationPaths:
    """Resolve the application boundary without creating directories or changing environment."""
    if environ.get("AVATAR_WORK_DIR"):
        raise ValueError(
            "Unset AVATAR_WORK_DIR and set avatar.workspace_root to the "
            "existing complete workspace directory so its data remains reachable."
        )
    if environ.get("ALPHAAVATAR_MODEL_CACHE"):
        raise ValueError(
            "Unset ALPHAAVATAR_MODEL_CACHE and set application.cache_root explicitly "
            "and preserve its models/ directory before switching the cache location."
        )
    return ApplicationPaths.from_root(environ.get("ALPHAAVATAR_HOME") or default_root)


def platform_application_root(environ: Mapping[str, str], home: Path) -> Path:
    if sys.platform == "win32":
        return Path(environ.get("LOCALAPPDATA") or home / "AppData" / "Local") / "AlphaAvatar"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "AlphaAvatar"
    return Path(environ.get("XDG_DATA_HOME") or home / ".local" / "share") / "alphaavatar"
