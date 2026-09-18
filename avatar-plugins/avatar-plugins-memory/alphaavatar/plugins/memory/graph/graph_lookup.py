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
from collections import defaultdict, deque
from typing import Any


def _read_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []

    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception as exc:
            raise RuntimeError(f"Invalid graph JSONL: {path}:{line_number}") from exc

        if not isinstance(row, dict):
            raise RuntimeError(f"Invalid graph row: {path}:{line_number}")

        rows.append(row)

    return rows


class GraphLookup:
    def __init__(self, graph_path: str | pathlib.Path) -> None:
        self._graph_path = pathlib.Path(graph_path)
        self._aliases = self._load_aliases()
        self._reverse_aliases = self._build_reverse_aliases()
        self._neighbors = self._load_neighbors()

    def _load_aliases(self) -> dict[str, str]:
        aliases: dict[str, str] = {}

        for row in _read_jsonl(self._graph_path / "aliases.jsonl"):
            alias = str(row.get("alias_key") or "").strip()
            canonical = str(row.get("canonical_key") or "").strip()
            if alias and canonical and alias != canonical:
                aliases[alias] = canonical

        return aliases

    def _build_reverse_aliases(self) -> dict[str, list[str]]:
        reverse: dict[str, list[str]] = defaultdict(list)

        for alias, canonical in self._aliases.items():
            reverse[canonical].append(alias)

        return dict(reverse)

    def _load_neighbors(self) -> dict[str, list[tuple[str, float]]]:
        neighbors: dict[str, list[tuple[str, float]]] = defaultdict(list)

        for row in _read_jsonl(self._graph_path / "links.jsonl"):
            source = str(row.get("source_key") or "").strip()
            target = str(row.get("target_key") or "").strip()

            if not source or not target or source == target:
                continue

            weight = float(row.get("weight", 1.0))
            neighbors[source].append((target, weight))
            neighbors[target].append((source, weight))

        return dict(neighbors)

    def resolve_keys(self, node_key: str) -> list[str]:
        node_key = str(node_key).strip()
        if not node_key:
            return []

        canonical = self._aliases.get(node_key, node_key)
        return list(
            dict.fromkeys(
                [
                    canonical,
                    node_key,
                    *self._reverse_aliases.get(canonical, []),
                ]
            )
        )

    def expand_node_keys(
        self,
        *,
        node_keys: list[str],
        max_hops: int = 1,
        max_neighbors_per_node: int = 16,
        min_weight: float = 0.0,
    ) -> list[str]:
        queue = deque((key, 0) for node_key in node_keys for key in self.resolve_keys(node_key))
        visited: set[str] = set()
        ordered: list[str] = []

        while queue:
            key, hop = queue.popleft()

            if key in visited:
                continue

            visited.add(key)
            ordered.append(key)

            if hop >= max_hops:
                continue

            neighbors = sorted(
                self._neighbors.get(key, []),
                key=lambda item: item[1],
                reverse=True,
            )
            for neighbor, weight in neighbors[:max_neighbors_per_node]:
                if weight >= min_weight and neighbor not in visited:
                    queue.append((neighbor, hop + 1))

        return ordered
