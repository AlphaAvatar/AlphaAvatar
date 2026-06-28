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
from typing import Any


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _json_loads(line: str) -> dict[str, Any] | None:
    try:
        data = json.loads(line)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _read_jsonl_map(path: pathlib.Path, key_field: str) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}

    out: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue

        item = _json_loads(line)
        if not item:
            continue

        key = str(item.get(key_field, "")).strip()
        if not key:
            continue

        out[key] = item

    return out


def _write_jsonl(path: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(_json_dumps(row) for row in rows)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _merge_unique(old: list[Any], new: list[Any], *, limit: int | None = None) -> list[Any]:
    seen = set()
    out = []

    for x in old + new:
        s = str(x)
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(x)

        if limit is not None and len(out) >= limit:
            break

    return out


def _link_key(source_key: str, target_key: str) -> str:
    # M3-Agent-style weak links do not need direction here.
    a, b = sorted([source_key, target_key])
    return f"{a}__{b}"


def _node_stub_from_graph_node(
    *,
    node: dict[str, Any],
    memory_id: str,
    session_id: str,
    object_ids: list[str],
    memory_type: str,
    timestamp: str,
) -> dict[str, Any]:
    node_key = str(node.get("key", "") or node.get("id", "")).strip()
    extra_data = node.get("extra_data") or {}

    return {
        "node_key": node_key,
        "type": str(node.get("type", "text")),
        "content": str(node.get("content", "")),
        "weight": float(node.get("weight", 1.0)),
        "count": 1,
        "first_seen": timestamp,
        "last_seen": timestamp,
        "memory_ids": [memory_id],
        "session_ids": [session_id],
        "object_ids": object_ids,
        "memory_types": [memory_type],
        "aliases": _as_list(extra_data.get("aliases")),
        "extra_data": extra_data,
    }


def _merge_node_stub(
    *,
    old: dict[str, Any],
    new: dict[str, Any],
) -> dict[str, Any]:
    old_count = int(old.get("count", 0))
    new_count = int(new.get("count", 1))

    old["count"] = old_count + new_count
    old["weight"] = max(float(old.get("weight", 1.0)), float(new.get("weight", 1.0)))

    if not old.get("content") and new.get("content"):
        old["content"] = new["content"]

    if str(new.get("last_seen", "")) >= str(old.get("last_seen", "")):
        old["last_seen"] = new.get("last_seen", old.get("last_seen"))

    if not old.get("first_seen"):
        old["first_seen"] = new.get("first_seen")

    old["memory_ids"] = _merge_unique(
        _as_list(old.get("memory_ids")),
        _as_list(new.get("memory_ids")),
        limit=256,
    )
    old["session_ids"] = _merge_unique(
        _as_list(old.get("session_ids")),
        _as_list(new.get("session_ids")),
        limit=256,
    )
    old["object_ids"] = _merge_unique(
        _as_list(old.get("object_ids")),
        _as_list(new.get("object_ids")),
        limit=256,
    )
    old["memory_types"] = _merge_unique(
        _as_list(old.get("memory_types")),
        _as_list(new.get("memory_types")),
        limit=32,
    )
    old["aliases"] = _merge_unique(
        _as_list(old.get("aliases")),
        _as_list(new.get("aliases")),
        limit=64,
    )

    extra = dict(old.get("extra_data") or {})
    extra.update(new.get("extra_data") or {})
    old["extra_data"] = extra

    return old


def _node_item_stub(
    *,
    node_key: str,
    memory_id: str,
    session_id: str,
    object_ids: list[str],
    memory_type: str,
    timestamp: str,
    topic: str | None,
) -> dict[str, Any]:
    return {
        "node_key": node_key,
        "memory_id": memory_id,
        "session_id": session_id,
        "object_ids": object_ids,
        "memory_type": memory_type,
        "timestamp": timestamp,
        "topic": topic,
    }


def _is_memory_item_key(key: str) -> bool:
    return str(key).startswith("memory_item:")


def save_memory_graph_stubs(
    *,
    graph_path: str | pathlib.Path,
    memory_items: list[dict[str, Any]],
) -> dict[str, Any]:
    graph_path = pathlib.Path(graph_path)
    graph_path.mkdir(parents=True, exist_ok=True)

    nodes_path = graph_path / "nodes.jsonl"
    links_path = graph_path / "links.jsonl"
    node_items_path = graph_path / "node_items.jsonl"

    nodes = _read_jsonl_map(nodes_path, "node_key")
    links = _read_jsonl_map(links_path, "link_key")

    # For node_items we use a compound key to avoid duplicates.
    node_items = _read_jsonl_map(node_items_path, "node_item_key")

    inserted_or_updated_nodes = 0
    inserted_or_updated_links = 0
    inserted_or_updated_node_items = 0

    for item in memory_items:
        memory_id = str(item.get("id", "")).strip()
        metadata = item.get("metadata", {}) or {}

        session_id = str(metadata.get("session_id", "")).strip()
        memory_type = str(metadata.get("memory_type", "")).strip()
        object_ids = metadata.get("object_ids") or []
        timestamp = str(metadata.get("ts", "")).strip()
        topic = metadata.get("topic")

        graph_nodes = metadata.get("graph_nodes") or []
        graph_links = metadata.get("graph_links") or []

        node_id_to_key: dict[str, str] = {}

        for node in graph_nodes:
            extra_data = node.get("extra_data") or {}

            # Keep memory_item nodes out of global node stubs.
            if extra_data.get("node_kind") == "memory_item":
                continue

            node_key = str(node.get("key", "") or node.get("id", "")).strip()
            node_id = str(node.get("id", "")).strip()

            if not node_key:
                continue

            if node_id:
                node_id_to_key[node_id] = node_key

            new_stub = _node_stub_from_graph_node(
                node=node,
                memory_id=memory_id,
                session_id=session_id,
                object_ids=object_ids,
                memory_type=memory_type,
                timestamp=timestamp,
            )

            if node_key in nodes:
                nodes[node_key] = _merge_node_stub(old=nodes[node_key], new=new_stub)
            else:
                nodes[node_key] = new_stub

            inserted_or_updated_nodes += 1

            node_item_key = f"{node_key}::{memory_id}"
            if node_item_key not in node_items:
                row = _node_item_stub(
                    node_key=node_key,
                    memory_id=memory_id,
                    session_id=session_id,
                    object_ids=object_ids,
                    memory_type=memory_type,
                    timestamp=timestamp,
                    topic=topic,
                )
                row["node_item_key"] = node_item_key
                node_items[node_item_key] = row
                inserted_or_updated_node_items += 1

        for link in graph_links:
            extra_data = link.get("extra_data") or {}

            source_key = str(link.get("source_key") or extra_data.get("source_key") or "").strip()

            target_key = str(link.get("target_key") or extra_data.get("target_key") or "").strip()

            if not source_key:
                source_key = node_id_to_key.get(str(link.get("source_id", "")).strip(), "")
            if not target_key:
                target_key = node_id_to_key.get(str(link.get("target_id", "")).strip(), "")

            if (
                not source_key
                or not target_key
                or source_key == target_key
                or _is_memory_item_key(source_key)
                or _is_memory_item_key(target_key)
            ):
                continue

            key = _link_key(source_key, target_key)

            new_link = {
                "link_key": key,
                "source_key": min(source_key, target_key),
                "target_key": max(source_key, target_key),
                "weight": float(link.get("weight", 1.0)),
                "count": 1,
                "first_seen": timestamp,
                "last_seen": timestamp,
                "memory_ids": [memory_id],
                "session_ids": [session_id],
                "memory_types": [memory_type],
                "extra_data": extra_data,
            }

            if key in links:
                old = links[key]
                old["count"] = int(old.get("count", 0)) + 1
                old["weight"] = max(float(old.get("weight", 1.0)), float(new_link["weight"]))
                old["last_seen"] = max(str(old.get("last_seen", "")), timestamp)
                old["memory_ids"] = _merge_unique(
                    _as_list(old.get("memory_ids")),
                    [memory_id],
                    limit=256,
                )
                old["session_ids"] = _merge_unique(
                    _as_list(old.get("session_ids")),
                    [session_id],
                    limit=256,
                )
                old["memory_types"] = _merge_unique(
                    _as_list(old.get("memory_types")),
                    [memory_type],
                    limit=32,
                )
                links[key] = old
            else:
                links[key] = new_link

            inserted_or_updated_links += 1

    _write_jsonl(nodes_path, sorted(nodes.values(), key=lambda x: str(x.get("node_key", ""))))
    _write_jsonl(links_path, sorted(links.values(), key=lambda x: str(x.get("link_key", ""))))
    _write_jsonl(
        node_items_path,
        sorted(node_items.values(), key=lambda x: str(x.get("node_item_key", ""))),
    )

    return {
        "nodes_file": str(nodes_path),
        "links_file": str(links_path),
        "node_items_file": str(node_items_path),
        "nodes": len(nodes),
        "links": len(links),
        "node_items": len(node_items),
        "updated_nodes": inserted_or_updated_nodes,
        "updated_links": inserted_or_updated_links,
        "updated_node_items": inserted_or_updated_node_items,
    }
