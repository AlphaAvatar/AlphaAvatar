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
from collections.abc import Iterable
from itertools import combinations

from alphaavatar.agents.memory.schemas import (
    GraphNodeMention,
    MemoryGraphLink,
    MemoryGraphNode,
    MemoryItem,
)

LOCAL_NODE_TYPES = {"face", "voice", "speaker", "object"}
GLOBAL_KEY_PREFIXES = (
    "user:",
    "tool:",
    "project:",
    "concept:",
    "artifact:",
    "image:",
    "audio:",
    "turn:",
    "memory_item:",
)


def _is_global_key(key: str) -> bool:
    return key.startswith(GLOBAL_KEY_PREFIXES)


def _is_scoped_local_key(key: str) -> bool:
    return ":local:" in key


def _normalize_node_type(node_type: str | None) -> str:
    value = str(node_type or "text").strip().lower()
    return "voice" if value == "speaker" else value


def _norm_text(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _scope_local_key(*, key: str, node_type: str, context_id: str) -> tuple[str, str]:
    key = str(key or "").strip()
    node_type = _normalize_node_type(node_type)

    if not key:
        return "", "unknown"
    if _is_global_key(key) or _is_scoped_local_key(key):
        return key, "global" if _is_global_key(key) else "context"

    if node_type in LOCAL_NODE_TYPES:
        local_id = key.split(":", 1)[1] if ":" in key else key
        return f"{node_type}:local:{context_id}:{local_id}", "context"

    return key, "global"


def _stable_key(*, node_type: str, content: str) -> str:
    raw = f"{node_type}:{_norm_text(content)}"
    digest = hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"{node_type}:{digest}"


def normalize_mention(
    mention: GraphNodeMention,
    *,
    context_id: str,
) -> MemoryGraphNode | None:
    content = str(mention.content or "").strip()
    if not content:
        return None

    node_type = _normalize_node_type(mention.type)
    raw_key = str(mention.key or "").strip()

    if raw_key:
        key, key_scope = _scope_local_key(key=raw_key, node_type=node_type, context_id=context_id)
    elif node_type in LOCAL_NODE_TYPES:
        digest = hashlib.sha256(
            f"{node_type}:{_norm_text(content)}".encode("utf-8", errors="ignore")
        ).hexdigest()[:16]
        key, key_scope = f"{node_type}:local:{context_id}:{digest}", "context"
    else:
        key, key_scope = _stable_key(node_type=node_type, content=content), "global"

    extra_data = {"key_scope": key_scope}
    if raw_key:
        extra_data["raw_key"] = raw_key

    return MemoryGraphNode(
        key=key,
        type=node_type,
        content=content,
        weight=mention.weight,
        extra_data=extra_data,
    )


def _memory_metadata(item: MemoryItem) -> dict:
    return {
        "memory_id": item.memory_id,
        "episode_id": item.context.episode_id,
        "context_id": item.context.context_id,
        "runtime_session_id": item.context.session_id,
        "owner_keys": [ref.key for ref in item.owner_refs],
        "participant_keys": [ref.key for ref in item.participant_refs],
        "memory_type": item.memory_type.value,
        "topic": item.topic,
        "created_at": item.created_at.isoformat(),
    }


def build_memory_item_node(item: MemoryItem) -> MemoryGraphNode:
    return MemoryGraphNode(
        key=f"memory_item:{item.memory_id}",
        type="text",
        content=item.value,
        weight=1.0,
        extra_data={"node_kind": "memory_item", **_memory_metadata(item)},
    )


def _is_memory_item_node(node: MemoryGraphNode) -> bool:
    return (node.extra_data or {}).get("node_kind") == "memory_item"


def build_graph_from_mentions(
    *,
    item: MemoryItem,
    mentions: Iterable[GraphNodeMention],
) -> tuple[list[MemoryGraphNode], list[MemoryGraphLink]]:
    item_node = build_memory_item_node(item)
    nodes_by_key = {item_node.key: item_node}

    for mention in mentions:
        node = normalize_mention(mention, context_id=item.context.context_id)
        if node is None:
            continue

        if old := nodes_by_key.get(node.key):
            old.weight = max(old.weight, node.weight)
            old.extra_data.update(node.extra_data)
        else:
            nodes_by_key[node.key] = node

    nodes = list(nodes_by_key.values())
    mention_nodes = [node for node in nodes if not _is_memory_item_node(node)]
    metadata = _memory_metadata(item)

    links = [
        MemoryGraphLink(
            source_id=item_node.id,
            target_id=node.id,
            source_key=item_node.key,
            target_key=node.key,
            weight=node.weight,
            extra_data={"link_kind": "memory_item_contains_node", **metadata},
        )
        for node in mention_nodes
    ]

    for left, right in combinations(mention_nodes[:12], 2):
        links.append(
            MemoryGraphLink(
                source_id=left.id,
                target_id=right.id,
                source_key=left.key,
                target_key=right.key,
                weight=min(left.weight, right.weight),
                extra_data={"link_kind": "co_occurs_in_memory_item", **metadata},
            )
        )

    return nodes, links
