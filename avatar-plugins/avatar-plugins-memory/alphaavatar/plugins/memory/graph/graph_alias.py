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


def _read_alias_map(path: pathlib.Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}

    out: dict[str, dict[str, Any]] = {}

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue

        row = _json_loads(line)
        if not row:
            continue

        alias_key = str(row.get("alias_key", "")).strip()
        canonical_key = str(row.get("canonical_key", "")).strip()

        if not alias_key or not canonical_key:
            continue

        out[alias_key] = row

    return out


def _write_aliases(path: pathlib.Path, aliases: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    rows = sorted(
        aliases.values(),
        key=lambda x: (
            str(x.get("canonical_key", "")),
            str(x.get("alias_key", "")),
        ),
    )

    text = "\n".join(_json_dumps(row) for row in rows)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def save_graph_aliases(
    *,
    graph_path: str | pathlib.Path,
    aliases: list[dict[str, Any]],
) -> dict[str, Any]:
    graph_path = pathlib.Path(graph_path)
    aliases_path = graph_path / "aliases.jsonl"

    alias_map = _read_alias_map(aliases_path)

    updated = 0
    skipped = 0
    conflicts: list[dict[str, Any]] = []

    for alias in aliases:
        alias_key = str(alias.get("alias_key", "")).strip()
        canonical_key = str(alias.get("canonical_key", "")).strip()

        if not alias_key or not canonical_key or alias_key == canonical_key:
            skipped += 1
            continue

        # local detector keys must already be scoped before aliasing
        if alias_key.startswith(("face:", "voice:", "object:")) and ":local:" not in alias_key:
            skipped += 1
            conflicts.append(
                {
                    "alias_key": alias_key,
                    "canonical_key": canonical_key,
                    "reason": "unscoped_local_key",
                }
            )
            continue

        old = alias_map.get(alias_key)

        if old:
            old_canonical = str(old.get("canonical_key", "")).strip()
            old_weight = float(old.get("weight", 0.0))
            new_weight = float(alias.get("weight", 0.0))

            # If conflict, only replace when new confidence is higher.
            if old_canonical and old_canonical != canonical_key and new_weight < old_weight:
                conflicts.append(
                    {
                        "alias_key": alias_key,
                        "old_canonical_key": old_canonical,
                        "new_canonical_key": canonical_key,
                        "old_weight": old_weight,
                        "new_weight": new_weight,
                        "reason": "lower_confidence_conflict",
                    }
                )
                skipped += 1
                continue

            merged = dict(old)
            merged.update(alias)
            alias_map[alias_key] = merged
        else:
            alias_map[alias_key] = alias

        updated += 1

    _write_aliases(aliases_path, alias_map)

    return {
        "aliases_file": str(aliases_path),
        "aliases": len(alias_map),
        "updated": updated,
        "skipped": skipped,
        "conflicts": conflicts,
    }
