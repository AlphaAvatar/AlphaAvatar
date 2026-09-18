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
from collections import defaultdict
from typing import Any

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


def _render_entry(item: MemoryItem) -> str:
    lines = [
        f"## Memory: {item.memory_id}",
        "",
        f"- **revision**: {item.revision}",
        f"- **kind**: {item.kind.value}",
        f"- **memory_type**: {item.memory_type.value}",
        f"- **scope**: {item.scope.key}",
        f"- **created_at**: {item.created_at.isoformat()}",
        f"- **updated_at**: {(item.updated_at or item.created_at).isoformat()}",
        f"- **owners**: {', '.join(ref.key for ref in item.owner_refs)}",
        f"- **participants**: {', '.join(ref.key for ref in item.participant_refs) or 'N/A'}",
        f"- **sources**: {', '.join(ref.key for ref in item.source_refs) or 'N/A'}",
        f"- **topic**: {item.topic or 'N/A'}",
        f"- **source_memory_ids**: {', '.join(item.source_memory_ids) or 'N/A'}",
        f"- **supersedes_memory_ids**: {', '.join(item.supersedes_memory_ids) or 'N/A'}",
        "",
        "### Content",
        "",
        *_wrap_text(item.value),
        "",
    ]

    if item.graph_nodes:
        lines.extend(
            [
                "### Graph Nodes",
                "",
                *_json_block([node.model_dump(mode="json") for node in item.graph_nodes]),
                "",
            ]
        )

    if item.graph_links:
        lines.extend(
            [
                "### Graph Links",
                "",
                *_json_block([link.model_dump(mode="json") for link in item.graph_links]),
                "",
            ]
        )

    if item.extra_data:
        lines.extend(["### Extra Data", "", *_json_block(item.extra_data), ""])

    return "\n".join(lines).rstrip()


def _split_entries(text: str) -> dict[str, tuple[int, str]]:
    marker = "## Memory: "
    starts = [index for index in range(len(text)) if text.startswith(marker, index)]
    entries: dict[str, tuple[int, str]] = {}

    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        raw = text[start:end].strip()
        lines = raw.splitlines()

        if not lines:
            continue

        memory_id = lines[0].removeprefix(marker).strip()
        revision = 0

        for line in lines[1:]:
            if not line.startswith("- **revision**: "):
                continue
            try:
                revision = int(line.removeprefix("- **revision**: ").strip())
            except ValueError:
                revision = 0
            break

        if memory_id:
            entries[memory_id] = (revision, raw)

    return entries


def _render_document(items: list[MemoryItem], entries: dict[str, tuple[int, str]]) -> str:
    context = items[0].context
    body = "\n\n".join(
        raw
        for _, raw in sorted(
            entries.values(),
            key=lambda value: value[1].splitlines()[0],
        )
    )

    return "\n".join(
        (
            "---",
            'type: "memory_context_export"',
            f"conversation_id: {json.dumps(context.conversation_id)}",
            f"context_id: {json.dumps(context.context_id)}",
            f"memory_count: {len(entries)}",
            "---",
            "",
            body,
            "",
        )
    )


def export_memory_items(export_dir: pathlib.Path, items: list[MemoryItem]) -> list[pathlib.Path]:
    groups: dict[tuple[str, str], list[MemoryItem]] = defaultdict(list)

    for item in items:
        groups[(item.context.conversation_id, item.context.context_id)].append(item)

    written: list[pathlib.Path] = []

    for (conversation_id, context_id), group in groups.items():
        path = (
            export_dir
            / "conversations"
            / _safe_name(conversation_id)
            / f"{_safe_name(context_id)}.md"
        )
        entries = _split_entries(path.read_text(encoding="utf-8")) if path.exists() else {}

        for item in group:
            current = entries.get(item.memory_id)
            if current is None or item.revision >= current[0]:
                entries[item.memory_id] = (item.revision, _render_entry(item))

        _write_atomic(path, _render_document(group, entries))
        written.append(path)

    return written
