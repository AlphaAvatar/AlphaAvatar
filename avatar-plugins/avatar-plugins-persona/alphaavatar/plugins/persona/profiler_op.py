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

import json
import uuid
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from alphaavatar.agents.utils import format_current_time

# --------------------------------- Patch models ---------------------------------
JSONScalar = str | int | float | bool


class ValueType(StrEnum):
    scalar = "scalar"
    list_item = "list_item"
    object_item = "object_item"


class PatchOp(BaseModel):
    op: Literal["set", "append", "remove", "clear"]
    path: str = Field(..., description="JSON Pointer-like path, e.g. /preferences/interests")
    value: JSONScalar | None = Field(
        default=None,
        description="For set/append/remove, provide a JSON value. For clear, omit or null.",
    )
    confidence: float = Field(0.7, ge=0, le=1, description="Confidence score in [0,1].")
    evidence: str = Field("", description="Quoted sentence or concise paraphrase.")
    source: str = Field("chat", description="Data source tag.")

    @model_validator(mode="after")
    def _validate_value_by_op(self):
        if self.op in ("set", "append", "remove") and self.value is None:
            raise ValueError(f"value is required when op='{self.op}'")
        if self.op == "append" and not isinstance(self.value, str):
            raise ValueError("append requires value to be a string.")
        if self.op == "remove" and not isinstance(self.value, str):
            raise ValueError("remove requires value to be a string.")
        if self.op == "clear":
            self.value = None
        return self


class ProfileDelta(BaseModel):
    ops: list[PatchOp] = Field(default_factory=list)


# --------------------------------- Path helpers ---------------------------------
def _ensure_parent(container: Any, tokens: list[str]) -> tuple[Any, str]:
    """Ensure parent path exists as dict; return (parent_obj, last_key)."""
    if not tokens:
        raise ValueError("Empty path tokens.")
    cur = container
    for t in tokens[:-1]:
        if isinstance(cur, dict):
            if t not in cur or cur[t] is None:
                cur[t] = {}
            cur = cur[t]
        else:
            raise TypeError(f"Parent at token '{t}' is not a dict; type={type(cur)}")
    return cur, tokens[-1]


def _ensure_list(container: dict[str, Any], tokens: list[str]) -> list[Any]:
    """Ensure list exists at path and return it; create [] if missing."""
    parent, key = _ensure_parent(container, tokens)
    if key not in parent or parent[key] is None:
        parent[key] = []
    if not isinstance(parent[key], list):
        parent[key] = [parent[key]]
    return parent[key]


def _norm_token(s: Any) -> str:
    """Normalize for case/whitespace-insensitive equality."""
    return " ".join(str(s).strip().lower().split())


# --------------------------------- OP helpers ---------------------------------
def parse_pointer(path: str) -> list[str]:
    """Split a JSON Pointer-like path into tokens (no RFC6901 escaping for brevity)."""
    if not path or path == "/":
        return []
    if path[0] == "/":
        path = path[1:]
    return [p for p in path.split("/") if p != ""]


def write_set(container: dict[str, Any], tokens: list[str], value: Any) -> None:
    """Set value at path (overwrite)."""
    parent, key = _ensure_parent(container, tokens)
    if isinstance(parent, dict):
        parent[key] = value
    else:
        raise TypeError(f"Cannot set at non-dict parent for key '{key}'")


def clear_path(container: dict[str, Any], tokens: list[str]) -> None:
    """Clear the value at path: None for scalars/objects, [] for lists (best effort)."""
    parent, key = _ensure_parent(container, tokens)
    cur = parent.get(key, None)
    if isinstance(cur, list):
        parent[key] = []
    else:
        parent[key] = None


def append_string(container: dict[str, Any], tokens: list[str], value: Any) -> None:
    """Append a string to a list at path with de-dup."""
    lst = _ensure_list(container, tokens)
    s = str(value)
    seen = {_norm_token(x): True for x in lst if isinstance(x, str)}
    if _norm_token(s) not in seen:
        lst.append(s)


def remove_string(container: dict[str, Any], tokens: list[str], value: Any) -> None:
    """Remove a string from a list at path (normalized match)."""
    parent, key = _ensure_parent(container, tokens)
    cur = parent.get(key, [])
    if not isinstance(cur, list):
        return
    norm = _norm_token(value)
    parent[key] = [x for x in cur if not (isinstance(x, str) and _norm_token(x) == norm)]


def post_fix_conflicts(data: dict[str, Any]) -> None:
    """
    Basic conflict cleanup:
    - If an item appears in both preferences.interests and preferences.dislikes, keep it in dislikes.
    - TODO: add more conflict items
    """
    prefs = data.get("preferences") or {}
    interests = prefs.get("interests") or []
    dislikes = prefs.get("dislikes") or []

    if isinstance(interests, list) and isinstance(dislikes, list):
        dislike_set = {_norm_token(x) for x in dislikes if isinstance(x, str)}
        cleaned = [
            x for x in interests if not (isinstance(x, str) and _norm_token(x) in dislike_set)
        ]
        if cleaned != interests:
            prefs["interests"] = cleaned
            data["preferences"] = prefs


# --------------------------------- Flatten / Rebuild for VectorStore ---------------------------------
def _is_primitive(x: Any) -> bool:
    return isinstance(x, str | int | float | bool)


def flatten_items(
    user_id: str, data: dict[str, Any], timestamp: dict[str, str], prefix: str = ""
) -> list[dict[str, Any]]:
    """
    Flatten a nested dict into vector-store "items".
    Each item dict has: id, page_content, metadata.
    """
    # TODO: item_id update
    items: list[dict[str, Any]] = []

    def walk(val: Any, path: str):
        # Scalars -> one item
        if _is_primitive(val) or val is None:
            if val is None or (isinstance(val, str) and val.strip() == ""):
                return  # skip empty
            meta_path = f"/{path}" if not path.startswith("/") else path
            ts = (
                timestamp[meta_path] if meta_path in timestamp else format_current_time("").time_str
            )
            items.append(
                {
                    "id": str(uuid.uuid4()),
                    "page_content": f"{path} = {val}",
                    "metadata": {
                        "user_id": user_id,
                        "path": meta_path,
                        "type": ValueType.scalar,
                        "value": str(val),
                        "json_value": json.dumps(val, ensure_ascii=False),
                        "ts": ts,
                    },
                }
            )
            return

        # Lists
        if isinstance(val, list):
            if len(val) == 0:
                return
            # list of primitives
            if all(_is_primitive(x) for x in val):
                for v in val:
                    _norm_token(v)
                    meta_path = f"/{path}" if not path.startswith("/") else path
                    ts = (
                        timestamp[meta_path]
                        if meta_path in timestamp
                        else format_current_time("").time_str
                    )
                    items.append(
                        {
                            "id": str(uuid.uuid4()),
                            "page_content": f"{path} += {v}",
                            "metadata": {
                                "user_id": user_id,
                                "path": meta_path,
                                "type": ValueType.list_item,
                                "value": str(v),
                                "json_value": json.dumps(v, ensure_ascii=False),
                                "ts": ts,
                            },
                        }
                    )
                return
            # list of objects
            for idx, obj in enumerate(val):
                meta_path = f"/{path}" if not path.startswith("/") else path
                ts = (
                    timestamp[meta_path]
                    if meta_path in timestamp
                    else format_current_time("").time_str
                )
                items.append(
                    {
                        "id": str(uuid.uuid4()),
                        "page_content": f"{path}[{idx}] = {json.dumps(obj, ensure_ascii=False)}",
                        "metadata": {
                            "user_id": user_id,
                            "path": f"{meta_path}[{idx}]",
                            "type": ValueType.object_item,
                            "index": idx,
                            "json_value": json.dumps(obj, ensure_ascii=False),
                            "ts": ts,
                        },
                    }
                )
            return

        # Dicts -> recurse
        if isinstance(val, dict):
            for k, v in val.items():
                key = f"{path}/{k}" if path else k
                walk(v, key)
            return

        # Fallback: store JSON string
        meta_path = f"/{path}" if not path.startswith("/") else path
        ts = timestamp[meta_path] if meta_path in timestamp else format_current_time("").time_str
        items.append(
            {
                "id": str(uuid.uuid4()),
                "page_content": f"{path} = {json.dumps(val, ensure_ascii=False)}",
                "metadata": {
                    "user_id": user_id,
                    "path": meta_path,
                    "type": ValueType.scalar,
                    "value": json.dumps(val, ensure_ascii=False),
                    "json_value": json.dumps(val, ensure_ascii=False),
                    "ts": ts,
                },
            }
        )

    walk(data, prefix.strip("/"))
    return items


def rebuild_from_items(items: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, str]]:
    """
    Reconstruct nested dict from vector-store items.
    """
    out: dict[str, Any] = {}
    timestamp: dict[str, str] = {}

    # First, handle object items (lists of objects) so we can merge indices
    # Update timestamp
    object_groups: dict[str, dict[int, Any]] = {}
    for it in items:
        meta = it.get("metadata", {})
        typ = meta.get("type")
        path = meta.get("path", "")
        if typ == ValueType.object_item:
            base_path, idx = path, meta.get("index", 0)
            # Strip '[idx]' from path -> map to list assembly key
            if base_path.endswith("]") and "[" in base_path:
                key_path = base_path[: base_path.rfind("[")]
                object_groups.setdefault(key_path, {})[int(idx)] = json.loads(
                    meta.get("json_value", "{}")
                )
                timestamp[key_path] = meta.get("ts", "")
            else:
                timestamp[path] = meta.get("ts", "")
        else:
            timestamp[path] = meta.get("ts", "")

    # Apply scalar and list_item first
    for it in items:
        meta = it.get("metadata", {})
        typ = meta.get("type")
        path = meta.get("path", "")
        tokens = parse_pointer(path)

        if typ == ValueType.scalar:
            val_json = meta.get("json_value")
            val = json.loads(val_json) if val_json is not None else meta.get("value")
            write_set(out, tokens, val)

        elif typ == ValueType.list_item:
            val_json = meta.get("json_value")
            val = json.loads(val_json) if val_json is not None else meta.get("value")
            lst = _ensure_list(out, tokens)
            # de-dup
            if isinstance(val, str | int | float | bool):
                s = str(val)
                seen = {_norm_token(x): True for x in lst if isinstance(x, str)}
                if _norm_token(s) not in seen:
                    lst.append(s)
            else:
                lst.append(val)

    # Now assemble lists of objects
    for key_path, idx_map in object_groups.items():
        tokens = parse_pointer(key_path)
        # Ensure parent list and fill by index order
        ordered = [idx_map[i] for i in sorted(idx_map.keys())]
        write_set(out, tokens, ordered)

    return out, timestamp
