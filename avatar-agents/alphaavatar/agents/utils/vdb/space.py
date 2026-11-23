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
"""The embedding space of a vector store: which model's vectors it holds.

Recorded when a store is made and checked each time it is opened, so vectors of two models
never share one store, whatever their dimension: a store recorded for another model is refused,
nothing in it changed. The record names the provider, the model, the dimensions asked of it
and the vectors' size; never a credential, the variable holding it or a server's address,
which change without changing the vectors. A store made before stores were recorded is taken
as the configured space only while empty, or holding vectors of the configured size, recorded
then as assumed: what model made them cannot be told.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class EmbeddingSpaceError(RuntimeError):
    """A store holds vectors of another embedding space than the configured one."""


@dataclass(frozen=True, slots=True)
class EmbeddingSpace:
    provider: str
    model: str
    dimensions: int | None = None  # Asked of the model, where it takes that.
    size: int | None = None  # Each vector's length: unknown until the model is asked.

    @classmethod
    def configured(cls, embedding: Mapping[str, Any], size: int | None = None) -> EmbeddingSpace:
        """The space a store's ``embedding`` setting names: its credentials and server aside."""
        extra = embedding.get("extra") or {}
        asked = extra.get("dimensions", extra.get("output_dimensionality"))
        return cls(
            str(embedding.get("provider") or "openai").strip().lower(),
            str(embedding.get("model") or "").strip(),
            int(asked) if asked is not None else None,
            size,
        )

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> EmbeddingSpace:
        return cls(
            str(record["provider"]),
            str(record["model"]),
            record.get("dimensions"),
            record.get("size"),
        )

    def same(self, other: EmbeddingSpace) -> bool:
        """The same model's vectors: provider, model and dimensions asked, and each known size."""
        sizes = self.size is None or other.size is None or self.size == other.size
        return (self.provider, self.model, self.dimensions) == (
            other.provider,
            other.model,
            other.dimensions,
        ) and sizes

    def describe(self) -> str:
        asked = f", {self.dimensions} dimensions asked" if self.dimensions is not None else ""
        size = f" ({self.size}-dimensional)" if self.size is not None else ""
        return f"{self.provider} {self.model}{asked}{size}"

    def record(self, *, store: str, setting: str, assumed: bool = False) -> dict[str, Any]:
        """What is kept beside the store: the space, the store, the setting that names it."""
        found = {
            "provider": self.provider,
            "model": self.model,
            "dimensions": self.dimensions,
            "size": self.size,
            "store": store,
            "setting": setting,
        }
        return found | ({"assumed": True} if assumed else {})


def refusal(store: str, setting: str, recorded: EmbeddingSpace, configured: EmbeddingSpace) -> str:
    embedding = f"{setting.rpartition('.')[0]}.embedding"
    return (
        f"{store} holds vectors of {recorded.describe()}; {embedding} names "
        f"{configured.describe()}. Vectors of two models never share a store: give {setting} "
        "another name, a separate index, or configure the embedding the store was made with. "
        "Nothing was changed: the store's vectors and the records they index stay."
    )


def claim(
    store: str,
    configured: EmbeddingSpace,
    *,
    label: str,
    setting: str,
    exists: Callable[[], bool],
    ensure: Callable[[], None],
    read: Callable[[], Mapping[str, Any] | None],
    write: Callable[[dict[str, Any]], None],
    count: Callable[[], int],
    size: Callable[[], int | None],
) -> None:
    """Open ``store`` for vectors of ``configured``: checked against its record before
    ``ensure`` makes it or readies it, then recorded if it was not.

    ``label`` is the store as messages name it; ``setting``, the setting it is named by, such as
    ``memory.vdb_config.collection_name``. The backend gives the store's operations.
    """
    recorded, assumed = None, False
    if exists():
        if (found := read()) is not None:
            recorded = EmbeddingSpace.from_record(found)
            if not recorded.same(configured):
                raise EmbeddingSpaceError(refusal(label, setting, recorded, configured))
        elif count() > 0:
            # Made before stores were recorded: only its vectors' size can be told.
            held = size()
            if held is not None and configured.size is not None and held != configured.size:
                held_space = EmbeddingSpace("unrecorded", "embedding", size=held)
                raise EmbeddingSpaceError(refusal(label, setting, held_space, configured))
            assumed = True

    ensure()

    if recorded is None:
        write(configured.record(store=store, setting=setting, assumed=assumed))
        if assumed:
            logger.warning(
                "%s holds vectors made before stores were recorded: taken as %s, which cannot "
                "be verified",
                label,
                configured.describe(),
            )


def _at(settings: Mapping[str, Any], path: str) -> Any:
    for key in path.split("."):
        settings = settings.get(key) if isinstance(settings, Mapping) else None
    return settings


def recorded_conflicts(settings: Mapping[str, Any], directories: Iterable[Path]) -> list[str]:
    """Each LanceDB store under ``directories`` an Avatar's ``settings`` (its sections as plain
    data) name with another embedding than its record holds: what ``claim`` refuses at start,
    told from the records alone, before anything is installed. Nothing is opened, so neither
    LanceDB nor the model is needed; the model's size, unknown until it is asked, is not compared,
    and a remote store, such as Qdrant's, is checked only as it is opened."""

    def named(value: Any) -> Iterable[str]:
        # The directories the settings name a LanceDB store's in, beside its embedding.
        if isinstance(value, Mapping):
            if isinstance(value.get("client_path"), str) and "embedding" in value:
                yield value["client_path"]
            for item in value.values():
                yield from named(item)

    found = []
    for directory in dict.fromkeys([*map(Path, directories), *map(Path, named(settings))]):
        for path in sorted(directory.rglob("*.embedding.json")):
            record = json.loads(path.read_text("utf-8"))
            setting = str(record.get("setting", ""))
            section = _at(settings, setting.partition(".vdb_config.")[0])
            if not isinstance(section, Mapping) or section.get("plugin") is None:
                continue  # No runner opens it.
            if section.get("enabled", True) is False:
                continue
            if _at(settings, setting) != record.get("store"):
                continue  # Configured to another store now.
            embedding = _at(settings, f"{setting.rpartition('.')[0]}.embedding")
            if not isinstance(embedding, Mapping):
                continue

            recorded = EmbeddingSpace.from_record(record)
            configured = EmbeddingSpace.configured(embedding)
            if not recorded.same(configured):
                label = f"LanceDB table {record['store']!r} in {path.parent}"
                found.append(refusal(label, setting, recorded, configured))
    return found
