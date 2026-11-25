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
from datetime import UTC, datetime
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


def _timestamp(value: datetime | str | None) -> str:
    if not value:
        return ""
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC).isoformat()


def _source(value: Any, metadata: dict | None = None) -> str:
    if metadata and metadata.get("source"):
        return metadata["source"]
    parts = value if isinstance(value, list) else [value]
    return max(
        (part.get("source", "chat") for part in parts if isinstance(part, dict)),
        key=lambda source: {"speech": 1, "face": 2, "chat": 3}.get(source, 0),
        default="chat" if metadata else "",
    )


def _priority(source: str) -> int:
    return {"speech": 1, "face": 2, "chat": 3}.get(source, 0)


def field_metadata(value: Any, metadata: dict | None = None) -> dict:
    result = deepcopy(metadata or {})
    parts = value if isinstance(value, list) else [value]
    stamp = max(
        (_timestamp(part.get("updated_at")) for part in parts if isinstance(part, dict)), default=""
    )
    result.setdefault("source", _source(value, metadata))
    result.setdefault("updated_at", stamp)
    result.setdefault("value_updated_at", stamp or _timestamp(result.get("updated_at")))
    result.setdefault("version", _timestamp(result.get("value_updated_at")))
    return result


def can_update_profile_field(
    details: Any, name: str, source: ProfileItemSource, updated_at: datetime
) -> bool:
    value = getattr(details, name, None)
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    metadata = field_metadata(value, getattr(details, "_field_metadata", {}).get(name))
    priority = _priority(source)
    previous = _priority(metadata.get("source", ""))
    return priority > previous or (
        priority == previous
        and _timestamp(updated_at) >= _timestamp(metadata.get("value_updated_at"))
    )


def merge_profile_field(value: Any, head: dict, incoming: dict) -> tuple[Any, dict]:
    """Merge one delta; field versions never erase independent list additions."""
    value = deepcopy(value)
    state = field_metadata(value, head)
    changes = incoming.get("changes", [])
    source = "chat" if changes else _source(incoming.get("value"), incoming)
    if _priority(source) < _priority(state.get("source", "")):
        return value, state

    if not changes:
        stamp = _timestamp(incoming["updated_at"])
        if _priority(source) == _priority(state.get("source", "")) and stamp < _timestamp(
            state.get("value_updated_at")
        ):
            return value, state
        # A newer snapshot supersedes deltas up to its timestamp, including explicit empties.
        return deepcopy(incoming.get("value")), {
            **deepcopy(incoming),
            "source": source,
            "version": stamp,
            "updated_at": max(_timestamp(state.get("updated_at")), stamp),
            "value_updated_at": stamp,
            "list_reset": stamp if isinstance(incoming.get("value"), list) else "",
        }

    previous_source = state.get("source", "")
    if _priority(source) > _priority(previous_source):
        state.update(
            version="", value_updated_at="", list_reset="", list_removed={}, list_versions={}
        )
    state["source"] = source
    for index, change in enumerate(changes):
        stamp = _timestamp(change.get("updated_at", incoming["updated_at"]))
        version = (
            stamp
            + "|"
            + str(change.get("sequence", index)).zfill(8)
            + "|"
            + change.get("id", incoming.get("change_id", ""))
        )
        operation, raw = change["op"], change.get("value")
        entry = {"value": raw, "source": source, "updated_at": stamp}
        if change.get("list"):
            current = value if isinstance(value, list) else []
            reset = state.get("list_reset", "")
            removed = state.setdefault("list_removed", {})
            versions = state.setdefault("list_versions", {})
            for part in current:
                versions.setdefault(_normalize(part["value"]), _timestamp(part["updated_at"]))
            if operation in {"set", "clear"}:
                if version <= reset:
                    continue
                retained = [
                    part
                    for part in current
                    if versions.get(_normalize(part["value"]), _timestamp(part["updated_at"]))
                    > version
                ]
                value = retained
                if operation == "set":
                    for part in raw:
                        key = _normalize(part)
                        if removed.get(key, "") <= version and key not in {
                            _normalize(item["value"]) for item in retained
                        }:
                            value.append({**entry, "value": part})
                            versions[key] = version
                state["list_reset"] = version
                state["list_removed"] = {
                    key: value for key, value in removed.items() if value > version
                }
                state["list_versions"] = {
                    _normalize(part["value"]): versions.get(
                        _normalize(part["value"]), _timestamp(part["updated_at"])
                    )
                    for part in value
                }
            elif operation == "append":
                key = _normalize(raw)
                if version <= max(reset, removed.get(key, ""), versions.get(key, "")):
                    continue
                value = [part for part in current if _normalize(part["value"]) != key]
                value.append(entry)
                versions[key] = version
                removed.pop(key, None)
            elif operation == "remove":
                key = _normalize(raw)
                if version <= max(reset, removed.get(key, "")):
                    continue
                removed[key] = version
                value = [
                    part
                    for part in current
                    if _normalize(part["value"]) != key
                    or versions.get(key, _timestamp(part["updated_at"])) > version
                ]
        else:
            if _priority(source) == _priority(previous_source) and version <= state.get(
                "version", ""
            ):
                continue
            value = apply_profile_changes(value, [change], stamp)
        state["version"] = max(state.get("version", ""), version)
        state["updated_at"] = max(_timestamp(state.get("updated_at")), stamp)
        state["value_updated_at"] = max(_timestamp(state.get("value_updated_at")), stamp)
        previous_source = source
    state["value"] = value
    return value, state


def merge_profile_items(existing: list[dict], updates: list[dict]) -> list[dict]:
    """Apply observation deltas against authoritative stored fields; leave other fields alone."""
    profile = rebuild_profile_items(existing)
    heads = {
        _field_name(item["metadata"]["path"]): item["metadata"]
        for item in existing
        if item.get("metadata", {}).get("type") == ProfileValueType.field
    }
    merged = []
    for item in updates:
        incoming = deepcopy(item["metadata"])
        name = _field_name(incoming["path"])
        head = heads.get(name, {})
        value, metadata = merge_profile_field(profile.get(name), head, incoming)
        metadata = {**incoming, **metadata, "value": value}
        if metadata == head:
            continue

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
        stamp = _timestamp(change.get("updated_at", updated_at))
        entry = {"value": raw, "source": "chat", "updated_at": stamp}
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
