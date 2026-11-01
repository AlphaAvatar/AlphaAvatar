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
from copy import deepcopy
from typing import Any


def snapshot_vdb_config(value: dict[str, Any]) -> dict[str, Any]:
    """Capture environment defaults without opening clients or changing process state."""
    config = deepcopy(value)
    if not config.get("client_path"):
        # Explicit nulls preserve an absent default when a launch payload is restored later.
        if not config.get("host"):
            config.setdefault("url", os.getenv("QDRANT_URL"))
        config.setdefault("api_key", os.getenv("QDRANT_API_KEY"))
    return config


def vdb_backend(config: dict[str, Any]) -> str:
    if config.get("url"):
        return "qdrant"
    if config.get("host"):
        if not config.get("port"):
            raise ValueError("A Qdrant host requires an explicit port")
        return "qdrant"
    return "lancedb"
