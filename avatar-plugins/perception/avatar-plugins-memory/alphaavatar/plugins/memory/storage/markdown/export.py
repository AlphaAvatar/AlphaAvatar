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

import json
import pathlib
from typing import Any

from alphaavatar.agents.memory.enums import MemoryScopeKind
from alphaavatar.agents.memory.schemas import MemoryItem


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_." else "_" for char in str(value))


def _write_atomic(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)


def _wrap_text(text: str) -> list[str]:
    fence = "````" if "```" in text else "```"
    return [f"{fence}text", text or "_empty_", fence]


def _json_block(value: Any) -> list[str]:
    return _wrap_text(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _read_revision(path: pathlib.Path) -> int:
    if not path.exists():
        return 0

    for line in path.read_text(encoding="utf-8").splitlines()[:16]:
        if line.startswith("revision:"):
            try:
                return int(line.partition(":")[2].strip())
            except ValueError:
                return 0
    return 0


def _render_document(item: MemoryItem) -> str:
    lines = [
        "---",
        'type: "memory_export"',
        f"memory_id: {json.dumps(item.memory_id)}",
        f"revision: {item.revision}",
        f"episode_id: {json.dumps(item.context.episode_id)}",
        f"context_id: {json.dumps(item.context.context_id)}",
        f"session_id: {json.dumps(item.context.session_id)}",
        f"scope: {json.dumps(item.scope.key)}",
        "---",
        "",
        f"# Memory: {item.memory_id}",
        "",
        f"- **kind**: {item.kind.value}",
        f"- **memory_type**: {item.memory_type.value}",
        f"- **created_at**: {item.created_at.isoformat()}",
        f"- **updated_at**: {(item.updated_at or item.created_at).isoformat()}",
        f"- **owners**: {', '.join(ref.key for ref in item.owner_refs)}",
        f"- **participants**: {', '.join(ref.key for ref in item.participant_refs) or 'N/A'}",
        f"- **sources**: {', '.join(ref.key for ref in item.source_refs) or 'N/A'}",
        f"- **topic**: {item.topic or 'N/A'}",
        f"- **source_memory_ids**: {', '.join(item.source_memory_ids) or 'N/A'}",
        f"- **supersedes_memory_ids**: {', '.join(item.supersedes_memory_ids) or 'N/A'}",
        "",
        "## Content",
        "",
        *_wrap_text(item.value),
        "",
    ]

    if item.graph_nodes:
        lines.extend(
            [
                "## Graph Nodes",
                "",
                *_json_block([node.model_dump(mode="json") for node in item.graph_nodes]),
                "",
            ]
        )

    if item.graph_links:
        lines.extend(
            [
                "## Graph Links",
                "",
                *_json_block([link.model_dump(mode="json") for link in item.graph_links]),
                "",
            ]
        )

    if item.extra_data:
        lines.extend(["## Extra Data", "", *_json_block(item.extra_data), ""])

    return "\n".join(lines).rstrip() + "\n"


def _export_paths(export_dir: pathlib.Path, item: MemoryItem) -> list[pathlib.Path]:
    filename = f"{_safe_name(item.memory_id)}.md"

    if item.scope.kind is MemoryScopeKind.OWNER:
        return [
            export_dir / "owners" / ref.kind.value / _safe_name(ref.id) / filename
            for ref in item.owner_refs
        ]

    if item.scope.kind is MemoryScopeKind.EPISODE:
        return [
            export_dir / "episodes" / _safe_name(item.context.episode_id) / "memories" / filename
        ]

    return [export_dir / "contexts" / _safe_name(item.context.context_id) / "memories" / filename]


def export_memory_items(export_dir: pathlib.Path, items: list[MemoryItem]) -> list[pathlib.Path]:
    written: list[pathlib.Path] = []

    for item in items:
        text = _render_document(item)

        for path in _export_paths(export_dir, item):
            if item.revision < _read_revision(path):
                continue
            _write_atomic(path, text)
            written.append(path)

    return list(dict.fromkeys(written))
