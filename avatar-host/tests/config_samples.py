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
"""Shared Host configuration samples: fictional credentials and small file helpers."""

from __future__ import annotations

import json
from pathlib import Path

SECRETS = {
    "MCP_DOCS_TOKEN": "tok-fictional-0042",
    "vdb": "vdb-fictional-0042",
    "url": "pw-fictional-0042",
    "query": "q-fictional-0042",
    "OPENAI_API_KEY": "sk-openai-fictional-0042",
}


CONFIG = {
    "avatar": {"id": "assistant", "introduction": f"Uses {SECRETS['vdb']} inline."},
    "memory": {"vdb_config": {"url": "https://vectors.invalid", "api_key": SECRETS["vdb"]}},
    "tools": {
        "mcp": {
            "enabled": True,
            "servers": {
                "docs": {
                    "url": f"https://user:{SECRETS['url']}@mcp.invalid/x?key={SECRETS['query']}",
                    "headers": {"Authorization": "Bearer <MCP_DOCS_TOKEN>"},
                }
            },
        }
    },
}


# config init's layout: each section's profile under configs/profiles/<bundle>/.
LAYOUT = {
    "host": "host/host",
    "runtime": "agent/runtime",
    "context": "plugins/foundation/context",
    "loop": "plugins/foundation/loop",
    "voice": "plugins/foundation/voice",
    "vision": "plugins/foundation/vision",
    "status": "plugins/perception/status",
    "router": "plugins/perception/router",
    "character": "plugins/perception/character",
    "memory": "plugins/perception/memory",
    "persona": "plugins/perception/persona",
    "tools": "plugins/tools/tools",
}
SECTIONS = tuple(LAYOUT)


def write(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value))
    return path


def files(root: Path) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*"))
