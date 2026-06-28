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
import json
import pathlib
from collections import defaultdict
from typing import Any

from alphaavatar.agents.utils import time_utils


def _safe_name(value: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_", ".") else "_" for c in str(value))


def _render_frontmatter(
    *,
    title: str,
    memory_scope: str,
    session_id: str = "",
    day: str = "",
    memory_count: int = 0,
) -> str:
    lines = [
        "---",
        f'title: "{title}"',
        f'type: "{memory_scope}"',
        f"memory_count: {memory_count}",
    ]

    if session_id:
        lines.append(f'session_id: "{session_id}"')
    if day:
        lines.append(f'day: "{day}"')

    lines += [
        "---",
        "",
    ]
    return "\n".join(lines)


def _wrap_text_block(text: str) -> list[str]:
    text = text or "_empty_"
    fence = "```"
    if "```" in text:
        fence = "````"
    return [f"{fence}text", text, fence]


def _render_json_block(value: Any) -> list[str]:
    return _wrap_text_block(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _render_memory_entry(item: dict[str, Any]) -> str:
    metadata = item.get("metadata", {}) or {}

    memory_id = str(item.get("id", "")).strip()
    page_content = str(item.get("page_content", "")).strip()
    session_id = str(metadata.get("session_id", "")).strip()
    object_ids = metadata.get("object_ids") or []
    topic = str(metadata.get("topic", "")).strip()
    ts = str(metadata.get("ts", "")).strip()
    memory_type = str(metadata.get("memory_type", "")).strip()
    graph_nodes = metadata.get("graph_nodes") or []
    graph_links = metadata.get("graph_links") or []
    extra_data = metadata.get("extra_data") or {}

    lines = [
        f"## Memory: {memory_id}",
        "",
        f"- **ts**: {ts}",
        f"- **memory_type**: {memory_type}",
        f"- **object_ids**: {', '.join(str(x) for x in object_ids) if object_ids else 'N/A'}",
        f"- **session_id**: {session_id}",
        f"- **topic**: {topic or 'N/A'}",
        "",
        "### Content",
        "",
        *_wrap_text_block(page_content),
        "",
    ]

    if graph_nodes:
        lines += [
            "### Graph Nodes",
            "",
            *_render_json_block(graph_nodes),
            "",
        ]

    if graph_links:
        lines += [
            "### Graph Links",
            "",
            *_render_json_block(graph_links),
            "",
        ]

    if extra_data:
        lines += [
            "### Extra Data",
            "",
            *_render_json_block(extra_data),
            "",
        ]

    return "\n".join(lines)


def _split_existing_entries(text: str) -> dict[str, dict[str, Any]]:
    """
    Split an existing markdown file into:
    - map of memory_id -> parsed entry dict:
        {
            "raw": "...full rendered section...",
            "ts": "...",
        }
    """
    marker = "\n## Memory: "
    if text.startswith("## Memory: "):
        rest = text
    else:
        idx = text.find("\n## Memory: ")
        if idx == -1:
            return {}
        rest = text[idx + 1 :]

    parts = rest.split(marker)
    entries: dict[str, dict[str, Any]] = {}

    if parts:
        first = parts[0]
        chunks = [first] + [f"## Memory: {p}" for p in parts[1:]]
    else:
        chunks = []

    normalized_chunks: list[str] = []
    for i, chunk in enumerate(chunks):
        if i == 0 and not chunk.startswith("## Memory: "):
            chunk = "## Memory: " + chunk
        normalized_chunks.append(chunk.strip() + "\n")

    for chunk in normalized_chunks:
        lines = chunk.splitlines()
        if not lines:
            continue

        first_line = lines[0].strip()
        memory_id = first_line.replace("## Memory: ", "", 1).strip()
        if not memory_id:
            continue

        ts = ""
        for line in lines:
            if line.startswith("- **ts**: "):
                ts = line.replace("- **ts**: ", "", 1).strip()
                break

        entries[memory_id] = {
            "raw": chunk,
            "ts": ts,
        }

    return entries


def _entry_sort_key(memory_id: str, entry: dict[str, Any]) -> tuple[str, str]:
    ts = str(entry.get("ts", "") or "")
    return (ts, memory_id)


def _merge_entries(
    existing_text: str,
    new_items: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """
    Merge old + new entries and return:
    - merged entries map
    - original prefix
    """
    entries = _split_existing_entries(existing_text)

    for item in new_items:
        memory_id = str(item.get("id", "")).strip()
        if not memory_id:
            continue

        metadata = item.get("metadata", {}) or {}
        ts = str(metadata.get("ts", "")).strip()

        entries[memory_id] = {
            "raw": _render_memory_entry(item),
            "ts": ts,
        }

    return entries


def _render_merged_document(
    *,
    frontmatter: str,
    entries: dict[str, dict[str, Any]],
) -> str:
    ordered_ids = sorted(
        entries.keys(),
        key=lambda mid: _entry_sort_key(mid, entries[mid]),
    )
    body = "\n\n".join(entries[mid]["raw"].rstrip() for mid in ordered_ids).strip()

    if body:
        return frontmatter.rstrip() + "\n\n" + body + "\n"

    return frontmatter.rstrip() + "\n"


def _is_avatar_memory_type(memory_type: Any) -> bool:
    value = str(memory_type)
    return value in {
        "Avatar",
        "MemoryType.Avatar",
        "Assistant Memory",
    } or value.endswith(".Avatar")


def save_memory_items_to_markdown(
    *,
    avatar_memory_path: str | pathlib.Path,
    session_memory_path: str | pathlib.Path,
    memory_items: list[dict[str, Any]],
) -> dict[str, list[str]]:
    """
    Save memory items into markdown files.

    Rules:
    - Avatar memory: grouped by day under avatar_memory_path
      file name: YYYY-MM-DD.md
    - Non-avatar memory: grouped by session_id under session_memory_path
      file name: <session_id>.md
    """
    avatar_memory_path = pathlib.Path(avatar_memory_path)
    session_memory_path = pathlib.Path(session_memory_path)

    avatar_memory_path.mkdir(parents=True, exist_ok=True)
    session_memory_path.mkdir(parents=True, exist_ok=True)

    avatar_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    session_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for item in memory_items:
        metadata = item.get("metadata", {}) or {}
        memory_type = str(metadata.get("memory_type", ""))
        session_id = str(metadata.get("session_id", "") or "unknown_session")
        ts = metadata.get("ts", "")

        is_avatar = _is_avatar_memory_type(memory_type)
        if is_avatar:
            day = time_utils.time_str_to_datetime(ts).strftime("%Y-%m-%d")
            avatar_groups[day].append(item)
        else:
            session_groups[session_id].append(item)

    written_avatar_files: list[str] = []
    written_session_files: list[str] = []

    # save avatar memory
    for day, items in avatar_groups.items():
        file_path = avatar_memory_path / f"{_safe_name(day)}.md"
        existing = file_path.read_text(encoding="utf-8") if file_path.exists() else ""

        merged_entries = _merge_entries(existing, items)

        frontmatter = _render_frontmatter(
            title=f"Avatar Memory - {day}",
            memory_scope="avatar_daily_memory",
            day=day,
            memory_count=len(merged_entries),
        )

        final_text = _render_merged_document(
            frontmatter=frontmatter,
            entries=merged_entries,
        )
        file_path.write_text(final_text, encoding="utf-8")
        written_avatar_files.append(str(file_path))

    # save session memory
    for session_id, items in session_groups.items():
        file_path = session_memory_path / f"{_safe_name(session_id)}.md"
        existing = file_path.read_text(encoding="utf-8") if file_path.exists() else ""

        merged_entries = _merge_entries(existing, items)

        frontmatter = _render_frontmatter(
            title=f"Session Memory - {session_id}",
            memory_scope="session_memory",
            session_id=session_id,
            memory_count=len(merged_entries),
        )

        final_text = _render_merged_document(
            frontmatter=frontmatter,
            entries=merged_entries,
        )
        file_path.write_text(final_text, encoding="utf-8")
        written_session_files.append(str(file_path))

    return {
        "avatar_files": written_avatar_files,
        "session_files": written_session_files,
    }
