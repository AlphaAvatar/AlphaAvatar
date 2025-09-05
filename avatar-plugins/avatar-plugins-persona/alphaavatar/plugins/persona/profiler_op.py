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

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


# --------------------------------- Patch models ---------------------------------
class PatchOp(BaseModel):
    op: Literal["set", "append", "remove", "clear"]
    path: str = Field(..., description="JSON Pointer-like path (e.g., '/preferences/interests').")
    value: Any | None = Field(None, description="New value; used by set/append/remove.")
    confidence: float = Field(0.7, ge=0, le=1, description="Confidence score in [0,1].")
    evidence: str = Field("", description="Quoted sentence or concise paraphrase.")
    source: str = Field("chat", description="Data source tag.")
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


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
