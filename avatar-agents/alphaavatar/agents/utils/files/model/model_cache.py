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
from pathlib import Path

MODEL_CACHE_ENV = "ALPHAAVATAR_MODEL_CACHE"
_DEFAULT_MODEL_CACHE_ROOT = Path("~/.cache/alphaavatar/models")


def model_cache_root() -> Path:
    value = os.getenv(MODEL_CACHE_ENV)
    return Path(value).expanduser() if value else _DEFAULT_MODEL_CACHE_ROOT.expanduser()


def build_model_cache_dir(
    *parts: str,
    create: bool = False,
) -> Path:
    path = model_cache_root()

    for part in parts:
        value = part.strip()
        candidate = Path(value)

        if (
            not value
            or value in {".", ".."}
            or candidate.is_absolute()
            or len(candidate.parts) != 1
        ):
            raise ValueError(f"Invalid model cache path component: {part!r}")

        path /= value

    if create:
        path.mkdir(parents=True, exist_ok=True)

    return path
