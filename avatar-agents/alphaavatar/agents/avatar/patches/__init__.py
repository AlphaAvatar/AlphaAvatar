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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..engine import AvatarEngine


def init_avatar_patches(engine: AvatarEngine) -> None:
    """Initialize avatar patches."""
    from .context_search_patch import install_context_search_patch

    install_context_search_patch(engine)


def init_avatar_worker() -> None:
    from livekit.agents.cli import _run

    from .worker_patch import run_avatar_worker

    _run.run_worker = run_avatar_worker


init_avatar_worker()
