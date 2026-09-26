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

from alphaavatar.agents.memory.schemas import MemoryItem


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _read_jsonl_map(path: pathlib.Path, key: str) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}

    out: dict[str, dict[str, Any]] = {}

    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception as exc:
            raise RuntimeError(f"Invalid graph JSONL: {path}:{line_number}") from exc

        if not isinstance(row, dict):
            raise RuntimeError(f"Invalid graph row: {path}:{line_number}")

        value = str(row.get(key) or "").strip()
        if value:
            out[value] = row

    return out


def _write_jsonl(path: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    text = "\n".join(_json_dumps(row) for row in rows)
    temp.write_text(text + ("\n" if text else ""), encoding="utf-8")
    temp.replace(path)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _is_memory_item_key(key: str) -> bool:
    return key.startswith("memory_item:")


def _link_key(left: str, right: str) -> str:
    return "__".join(sorted((left, right)))


def _memory_record(item: MemoryItem) -> dict[str, Any]:
    return {
        "memory_id": item.memory_id,
        "revision": item.revision,
        "created_at": item.created_at.isoformat(),
        "updated_at": (item.updated_at or item.created_at).isoformat(),
        "nodes": [
            node.model_dump(mode="json")
            for node in item.graph_nodes
            if not _is_memory_item_key(node.key)
        ],
        "links": [
            link.model_dump(mode="json")
            for link in item.graph_links
            if not _is_memory_item_key(link.source_key) and not _is_memory_item_key(link.target_key)
        ],
    }


def _aggregate(
    records: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes: dict[str, dict[str, Any]] = {}
    links: dict[str, dict[str, Any]] = {}

    for record in records.values():
        memory_id = str(record["memory_id"])
        created_at = str(record.get("created_at") or "")
        updated_at = str(record.get("updated_at") or created_at)

        for node in record.get("nodes") or []:
            key = str(node.get("key") or node.get("id") or "").strip()
            if not key:
                continue

            aliases = [
                str(value)
                for value in _as_list((node.get("extra_data") or {}).get("aliases"))
                if value
            ]
            current = nodes.get(key)

            if current is None:
                nodes[key] = {
                    "node_key": key,
                    "type": str(node.get("type") or "text"),
                    "content": str(node.get("content") or ""),
                    "weight": float(node.get("weight", 1.0)),
                    "first_seen": created_at,
                    "last_seen": updated_at,
                    "memory_ids": [memory_id],
                    "aliases": list(dict.fromkeys(aliases)),
                    "extra_data": dict(node.get("extra_data") or {}),
                }
                continue

            current["weight"] = max(float(current["weight"]), float(node.get("weight", 1.0)))
            current["first_seen"] = min(str(current["first_seen"]), created_at)
            current["last_seen"] = max(str(current["last_seen"]), updated_at)
            current["memory_ids"] = list(dict.fromkeys([*current["memory_ids"], memory_id]))
            current["aliases"] = list(dict.fromkeys([*current["aliases"], *aliases]))
            current["extra_data"].update(node.get("extra_data") or {})

            if not current["content"] and node.get("content"):
                current["content"] = str(node["content"])

        for link in record.get("links") or []:
            source_key = str(link.get("source_key") or "").strip()
            target_key = str(link.get("target_key") or "").strip()

            if not source_key or not target_key or source_key == target_key:
                continue

            key = _link_key(source_key, target_key)
            left, right = sorted((source_key, target_key))
            current = links.get(key)

            if current is None:
                links[key] = {
                    "link_key": key,
                    "source_key": left,
                    "target_key": right,
                    "weight": float(link.get("weight", 1.0)),
                    "first_seen": created_at,
                    "last_seen": updated_at,
                    "memory_ids": [memory_id],
                    "extra_data": dict(link.get("extra_data") or {}),
                }
                continue

            current["weight"] = max(float(current["weight"]), float(link.get("weight", 1.0)))
            current["first_seen"] = min(str(current["first_seen"]), created_at)
            current["last_seen"] = max(str(current["last_seen"]), updated_at)
            current["memory_ids"] = list(dict.fromkeys([*current["memory_ids"], memory_id]))
            current["extra_data"].update(link.get("extra_data") or {})

    for row in nodes.values():
        row["count"] = len(row["memory_ids"])

    for row in links.values():
        row["count"] = len(row["memory_ids"])

    return (
        sorted(nodes.values(), key=lambda row: row["node_key"]),
        sorted(links.values(), key=lambda row: row["link_key"]),
    )


def export_memory_graph(graph_dir: pathlib.Path, items: list[MemoryItem]) -> None:
    graph_dir.mkdir(parents=True, exist_ok=True)
    records_path = graph_dir / "memories.jsonl"
    records = _read_jsonl_map(records_path, "memory_id")

    for item in items:
        current = records.get(item.memory_id)
        if current is None or item.revision >= int(current.get("revision") or 0):
            records[item.memory_id] = _memory_record(item)

    ordered_records = sorted(records.values(), key=lambda row: row["memory_id"])
    nodes, links = _aggregate(records)

    _write_jsonl(records_path, ordered_records)
    _write_jsonl(graph_dir / "nodes.jsonl", nodes)
    _write_jsonl(graph_dir / "links.jsonl", links)
