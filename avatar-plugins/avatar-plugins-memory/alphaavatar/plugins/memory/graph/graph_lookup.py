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
from collections import defaultdict, deque
from typing import Any


def _json_loads(line: str) -> dict[str, Any] | None:
    try:
        data = json.loads(line)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _read_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue

        item = _json_loads(line)
        if item:
            rows.append(item)

    return rows


def _norm_list(value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    out: list[str] = []
    seen: set[str] = set()

    for x in values:
        s = str(x).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)

    return out


class GraphLookup:
    def __init__(self, graph_path: str | pathlib.Path):
        self.graph_path = pathlib.Path(graph_path)

        self.nodes_path = self.graph_path / "nodes.jsonl"
        self.links_path = self.graph_path / "links.jsonl"
        self.node_items_path = self.graph_path / "node_items.jsonl"
        self.aliases_path = self.graph_path / "aliases.jsonl"

        self._aliases = self._load_aliases()
        self._reverse_aliases = self._build_reverse_aliases()
        self._neighbors = self._load_neighbors()
        self._node_items = self._load_node_items()

    def _load_aliases(self) -> dict[str, str]:
        aliases: dict[str, str] = {}

        for row in _read_jsonl(self.aliases_path):
            alias_key = str(row.get("alias_key", "")).strip()
            canonical_key = str(row.get("canonical_key", "")).strip()

            if alias_key and canonical_key and alias_key != canonical_key:
                aliases[alias_key] = canonical_key

        return aliases

    def _build_reverse_aliases(self) -> dict[str, list[str]]:
        reverse: dict[str, list[str]] = defaultdict(list)

        for alias_key, canonical_key in self._aliases.items():
            reverse[canonical_key].append(alias_key)

        return dict(reverse)

    def _load_neighbors(self) -> dict[str, list[tuple[str, float]]]:
        neighbors: dict[str, list[tuple[str, float]]] = defaultdict(list)

        for row in _read_jsonl(self.links_path):
            source_key = str(row.get("source_key", "")).strip()
            target_key = str(row.get("target_key", "")).strip()
            weight = float(row.get("weight", 1.0))

            if not source_key or not target_key or source_key == target_key:
                continue

            neighbors[source_key].append((target_key, weight))
            neighbors[target_key].append((source_key, weight))

        return dict(neighbors)

    def _load_node_items(self) -> dict[str, list[dict[str, Any]]]:
        node_items: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for row in _read_jsonl(self.node_items_path):
            node_key = str(row.get("node_key", "")).strip()
            if not node_key:
                continue
            node_items[node_key].append(row)

        return dict(node_items)

    def resolve_keys(self, node_key: str) -> list[str]:
        """
        Return canonical key + known aliases.
        This avoids rewriting VDB immediately after merge.
        """
        node_key = str(node_key).strip()
        if not node_key:
            return []

        canonical = self._aliases.get(node_key, node_key)

        keys = [canonical, node_key]
        keys.extend(self._reverse_aliases.get(canonical, []))

        out: list[str] = []
        seen: set[str] = set()
        for key in keys:
            if key and key not in seen:
                seen.add(key)
                out.append(key)

        return out

    def expand_node_keys(
        self,
        *,
        node_keys: list[str],
        max_hops: int = 1,
        max_neighbors_per_node: int = 16,
        min_weight: float = 0.0,
    ) -> list[str]:
        """
        Expand graph nodes through weak links.

        max_hops=0: only resolved keys
        max_hops=1: include direct neighbors
        max_hops=2: include neighbors of neighbors
        """
        start_keys: list[str] = []
        for key in node_keys:
            start_keys.extend(self.resolve_keys(key))

        visited: set[str] = set()
        ordered: list[str] = []

        queue = deque((key, 0) for key in start_keys)

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
                key=lambda x: x[1],
                reverse=True,
            )

            for neighbor_key, weight in neighbors[:max_neighbors_per_node]:
                if weight < min_weight:
                    continue
                if neighbor_key not in visited:
                    queue.append((neighbor_key, hop + 1))

        return ordered

    def find_memory_ids_by_node_keys(
        self,
        *,
        node_keys: list[str],
        object_ids: list[str] | None = None,
        session_id: str | None = None,
        memory_type: str | None = None,
        limit: int = 100,
    ) -> list[str]:
        wanted_objects = set(_norm_list(object_ids))

        out: list[str] = []
        seen: set[str] = set()

        for node_key in node_keys:
            for row in self._node_items.get(node_key, []):
                if session_id and str(row.get("session_id", "")) != session_id:
                    continue

                if memory_type and str(row.get("memory_type", "")) != memory_type:
                    continue

                if wanted_objects:
                    row_objects = set(_norm_list(row.get("object_ids")))
                    if not (wanted_objects & row_objects):
                        continue

                memory_id = str(row.get("memory_id", "")).strip()
                if not memory_id or memory_id in seen:
                    continue

                seen.add(memory_id)
                out.append(memory_id)

                if len(out) >= limit:
                    return out

        return out
