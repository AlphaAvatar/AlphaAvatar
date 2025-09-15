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


class PatchOp(BaseModel):
    op: Literal["set", "append", "remove", "clear"]
    path: str = Field(..., description="JSON Pointer-like path, e.g. /name")
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
        if self.op in ("append", "remove") and not isinstance(self.value, str):
            raise ValueError(f"{self.op} requires value to be a string.")
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
    """Clear the value at path: '' for strings, [] for lists, None otherwise."""
    parent, key = _ensure_parent(container, tokens)
    cur = parent.get(key, None)
    if isinstance(cur, list):
        parent[key] = []
    elif isinstance(cur, str) or cur is None:
        parent[key] = ""
    else:
        parent[key] = None


def append_string(container: dict[str, Any], tokens: list[str], value: Any) -> None:
    """Append a string to a list at path with de-dup."""
    lst = _ensure_list(container, tokens)
    s = str(value)
    seen = {_norm_token(x): True for x in lst if isinstance(x, str)}
    if _norm_token(s) not in seen:
        lst.append(s)


def append_text(container: dict[str, Any], tokens: list[str], value: Any, sep: str = " ") -> None:
    """
    Append text to a STRING field at path (like '+='):
      - If current is None or empty -> set to value
      - Else -> concatenate with a single separator (default space)
    """
    parent, key = _ensure_parent(container, tokens)
    s = str(value)
    cur = parent.get(key)
    if cur is None or (isinstance(cur, str) and cur.strip() == ""):
        parent[key] = s
        return
    if isinstance(cur, list):
        lst = _ensure_list(container, tokens)
        if _norm_token(s) not in {_norm_token(x) for x in lst if isinstance(x, str)}:
            lst.append(s)
        return

    cur_str = str(cur)
    if cur_str.endswith((" ", sep)):
        parent[key] = f"{cur_str}{s}"
    else:
        parent[key] = f"{cur_str}{sep}{s}"


def remove_string(container: dict[str, Any], tokens: list[str], value: Any) -> None:
    """Remove a string from a list at path (normalized match)."""
    parent, key = _ensure_parent(container, tokens)
    cur = parent.get(key, [])
    if not isinstance(cur, list):
        return
    norm = _norm_token(value)
    parent[key] = [x for x in cur if not (isinstance(x, str) and _norm_token(x) == norm)]


# --------------------------------- Flatten / Rebuild for VectorStore ---------------------------------
def _is_primitive(x: Any) -> bool:
    return isinstance(x, str | int | float | bool)


def flatten_items(
    user_id: str, data: dict[str, Any], timestamp: dict[str, str], prefix: str = ""
) -> list[dict[str, Any]]:
    """
    Flatten a FLAT dict (top-level keys only) into vector-store "items".
    Each item dict has: id, page_content, metadata.

    Rules:
      - Scalars -> one item: "path = value"
      - list of primitives -> items per element: "path += element"
      - Other types (dict / list of non-primitives / objects) -> JSON-string as scalar
      - Skip None or empty-string scalars
    """
    items: list[dict[str, Any]] = []
    base = prefix.strip("/")

    def _mk_path(key: str) -> tuple[str, str]:
        path = f"{base}/{key}" if base else key
        path = path.strip("/")
        meta_path = f"/{path}"
        return path, meta_path

    for key, val in (data or {}).items():
        path, meta_path = _mk_path(key)
        ts = timestamp.get(meta_path, format_current_time("").time_str)

        # Skip empty scalars
        if val is None or (isinstance(val, str) and val.strip() == ""):
            continue

        # Scalars
        if _is_primitive(val):
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
            continue

        # Lists
        if isinstance(val, list):
            if not val:
                continue
            if all(_is_primitive(x) for x in val):
                for v in val:
                    if v is None or (isinstance(v, str) and v.strip() == ""):
                        continue
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
                continue

            val_json = json.dumps(val, ensure_ascii=False)
            items.append(
                {
                    "id": str(uuid.uuid4()),
                    "page_content": f"{path} = {val_json}",
                    "metadata": {
                        "user_id": user_id,
                        "path": meta_path,
                        "type": ValueType.scalar,
                        "value": val_json,
                        "json_value": val_json,
                        "ts": ts,
                    },
                }
            )
            continue

        try:
            val_json = json.dumps(val, ensure_ascii=False)
        except TypeError:
            val_json = str(val)
        items.append(
            {
                "id": str(uuid.uuid4()),
                "page_content": f"{path} = {val_json}",
                "metadata": {
                    "user_id": user_id,
                    "path": meta_path,
                    "type": ValueType.scalar,
                    "value": val_json,
                    "json_value": val_json,
                    "ts": ts,
                },
            }
        )

    return items


def rebuild_from_items(items: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, str]]:
    """
    Reconstruct (flatten) dict from vector-store items.

    Note:
    - Only handles ValueType.scalar and ValueType.list_item.
    - For list_item: accumulate into list[str] using string deduplication rules.
    - No longer assembles object lists or nested structures.
    """
    out: dict[str, Any] = {}
    timestamp: dict[str, str] = {}

    for it in items:
        meta = it.get("metadata", {})
        typ = meta.get("type")
        path = meta.get("path", "")
        tokens = parse_pointer(path)
        timestamp[path] = meta.get("ts", "")

        if typ == ValueType.scalar:
            val_json = meta.get("json_value")
            val = json.loads(val_json) if val_json is not None else meta.get("value")
            write_set(out, tokens, val)

        elif typ == ValueType.list_item:
            val_json = meta.get("json_value")
            val = json.loads(val_json) if val_json is not None else meta.get("value")
            lst = _ensure_list(out, tokens)
            # de-dup（仅对字符串；其他类型直接 append）
            if isinstance(val, str | int | float | bool):
                s = str(val)
                seen = {_norm_token(x): True for x in lst if isinstance(x, str)}
                if _norm_token(s) not in seen:
                    lst.append(s)
            else:
                lst.append(val)

    return out, timestamp
