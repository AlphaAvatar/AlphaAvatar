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

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from alphaavatar.agents.persona.schemas import ProfileItemSource


class ProfileValueType(StrEnum):
    scalar = "scalar"
    list_item = "list_item"


def _datetime_iso(value: datetime | str) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        return value
    raise TypeError(f"Unsupported datetime value: {type(value).__name__}")


def _source_value(value: ProfileItemSource | str) -> str:
    return value.value if isinstance(value, ProfileItemSource) else str(value)


def _field_name(path: str) -> str:
    name = path.strip("/")
    if not name or "/" in name:
        raise ValueError(f"Profile path must contain exactly one field: {path!r}")
    return name


def _normalize(value: Any) -> str:
    return " ".join(str(value).strip().lower().split())


def flatten_profile_items(user_id: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    for field, item in data.items():
        path = f"/{field}"

        if isinstance(item, dict):
            value = item.get("value")
            if value is None or isinstance(value, str) and not value.strip():
                continue

            updated_at = item.get("updated_at")
            if updated_at is None:
                raise ValueError(f"Profile item {path!r} is missing updated_at")

            items.append(
                {
                    "id": str(uuid4()),
                    "page_content": f"{field} = {value}",
                    "metadata": {
                        "user_id": user_id,
                        "path": path,
                        "type": ProfileValueType.scalar,
                        "value": str(value),
                        "source": _source_value(item.get("source", ProfileItemSource.chat)),
                        "updated_at": _datetime_iso(updated_at),
                    },
                }
            )
            continue

        if not isinstance(item, list):
            continue

        for entry in item:
            value = entry.get("value")
            if value is None or isinstance(value, str) and not value.strip():
                continue

            updated_at = entry.get("updated_at")
            if updated_at is None:
                raise ValueError(f"Profile item {path!r} is missing updated_at")

            items.append(
                {
                    "id": str(uuid4()),
                    "page_content": f"{field} += {value}",
                    "metadata": {
                        "user_id": user_id,
                        "path": path,
                        "type": ProfileValueType.list_item,
                        "value": str(value),
                        "source": _source_value(entry.get("source", ProfileItemSource.chat)),
                        "updated_at": _datetime_iso(updated_at),
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

    return profile
