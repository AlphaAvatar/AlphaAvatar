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

import hashlib
import json
from copy import deepcopy
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from alphaavatar.agents.persona.schemas import ProfileItemSource


class ProfileValueType(StrEnum):
    field = "field"
    scalar = "scalar"
    list_item = "list_item"


def _field_name(path: str) -> str:
    name = path.strip("/")
    if not name or "/" in name:
        raise ValueError(f"Profile path must contain exactly one field: {path!r}")
    return name


def _normalize(value: Any) -> str:
    return " ".join(str(value).strip().lower().split())


def flatten_profile_items(
    user_id: str,
    data: dict[str, Any],
    *,
    fields: frozenset[str],
    updated_at: dict[str, datetime],
    operations: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Each changed field has one stable row; absence never deletes unrelated fields."""
    items = []
    for field in sorted(fields):
        value = data.get(field)
        identity = json.dumps([user_id, field], ensure_ascii=False, separators=(",", ":"))
        changes = (operations or {}).get(field, [])
        change = json.dumps(
            [identity, value, changes, updated_at[field].isoformat()], sort_keys=True
        )
        items.append(
            {
                "id": str(uuid5(NAMESPACE_URL, identity)),
                "page_content": f"{field} = {json.dumps(value, ensure_ascii=False)}",
                "metadata": {
                    "user_id": user_id,
                    "path": f"/{field}",
                    "type": ProfileValueType.field,
                    "value": value,
                    "updated_at": updated_at[field].isoformat(),
                    "changes": changes,
                    "change_id": hashlib.sha256(change.encode()).hexdigest(),
                },
            }
        )
    return items


def rebuild_profile_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    profile: dict[str, Any] = {}

    for item in items:
        metadata = item.get("metadata", {})
        field = _field_name(str(metadata.get("path", "")))
        value = metadata.get("value")
        updated_at = metadata.get("updated_at")

        if updated_at is None:
            raise ValueError(f"Profile item '/{field}' is missing updated_at")

        if metadata.get("type") == ProfileValueType.field:
            continue

        entry = {
            "value": value,
            "source": metadata.get("source", ProfileItemSource.chat),
            "updated_at": updated_at,
        }

        if metadata.get("type") == ProfileValueType.scalar:
            profile[field] = entry
            continue

        if metadata.get("type") != ProfileValueType.list_item:
            continue

        values = profile.setdefault(field, [])
        if _normalize(value) not in {_normalize(existing["value"]) for existing in values}:
            values.append(entry)

    # Field snapshots supersede older scalar/list rows without deleting those records.
    for item in items:
        metadata = item.get("metadata", {})
        if metadata.get("type") == ProfileValueType.field:
            profile[_field_name(str(metadata["path"]))] = metadata.get("value")
    return profile


def merge_profile_items(existing: list[dict], updates: list[dict]) -> list[dict]:
    """Apply observation deltas to this user's stored fields without importing another base."""
    profile = rebuild_profile_items(existing)
    heads = {
        _field_name(item["metadata"]["path"]): item["metadata"]
        for item in existing
        if item.get("metadata", {}).get("type") == ProfileValueType.field
    }
    merged = []
    for item in updates:
        metadata = deepcopy(item["metadata"])
        name = _field_name(metadata["path"])
        head = heads.get(name, {})
        if head.get("updated_at", "") > metadata["updated_at"]:
            continue
        if metadata.get("change_id") and metadata["change_id"] == head.get("change_id"):
            continue
        value = deepcopy(profile.get(name))
        changes = metadata.get("changes", [])
        if not changes:
            value = metadata.get("value")
        value = apply_profile_changes(value, changes, metadata["updated_at"])
        metadata["value"] = value
        profile[name], heads[name] = value, metadata
        merged.append(
            {
                **item,
                "metadata": metadata,
                "page_content": f"{name} = {json.dumps(value, ensure_ascii=False)}",
            }
        )
    return merged


def apply_profile_changes(value: Any, changes: list[dict], updated_at: str) -> Any:
    value = deepcopy(value)
    for change in changes:
        operation, raw = change["op"], change.get("value")
        entry = {"value": raw, "source": "chat", "updated_at": updated_at}
        if operation == "clear":
            value = [] if change["list"] else None
        elif operation == "set":
            value = [{**entry, "value": part} for part in raw] if isinstance(raw, list) else entry
        elif operation == "append" and change["list"]:
            value = value if isinstance(value, list) else []
            if _normalize(raw) not in {_normalize(part["value"]) for part in value}:
                value.append(entry)
        elif operation == "append":
            current = str(value.get("value", "")) if isinstance(value, dict) else ""
            value = {**entry, "value": f"{current} {raw}".strip()}
        elif operation == "remove" and isinstance(value, list):
            value = [part for part in value if _normalize(part["value"]) != _normalize(raw)]
    return value
