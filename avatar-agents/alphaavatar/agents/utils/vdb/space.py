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
never share one store, whatever their dimension: a store recorded for another model, or holding
vectors of another size, is refused before anything changes. The record names the provider,
the model, the dimensions asked of it and the vectors' size; never a credential, the variable
holding it or a server's address, which change without changing the vectors.

A record is only what holds a record's fields for its store: anything else of its name is
refused and left as it is. Hosts sharing a store record it at once safely: each records its own
model without overwriting another's, then reads what is recorded; one finding another model
takes its own back and refuses, so two models never both open a store.

A store made before stores were recorded is taken as the configured space only while its
vectors are of the configured size, recorded then as assumed if it holds any: what model made
them cannot be told.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MARK = "alphaavatar.embedding_space"  # A record's own field: the version of its layout.
_FIELDS = frozenset({"provider", "model", "dimensions", "size", "store", "setting"})
_OPTIONAL = frozenset({MARK, "assumed", "client_path"})


class EmbeddingSpaceError(RuntimeError):
    """A store holds vectors of another embedding space than the configured one, or what is
    named as its record is not one."""


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

    def record(
        self, *, store: str, setting: str, assumed: bool = False, client_path: str | None = None
    ) -> dict[str, Any]:
        """What is kept beside the store: the space, the store, the setting that names it, and
        the directory its settings named, if they named one."""
        found = {
            MARK: 1,
            "provider": self.provider,
            "model": self.model,
            "dimensions": self.dimensions,
            "size": self.size,
            "store": store,
            "setting": setting,
            "client_path": client_path,
        }
        return found | ({"assumed": True} if assumed else {})


def is_record(found: Any, *, store: str, marked: bool) -> bool:
    """Whether ``found`` is a record of ``store``: a record's fields and nothing else, with its
    mark (``marked``) or, as the version before marks wrote one, without."""
    if not isinstance(found, Mapping) or set(found) - _OPTIONAL != _FIELDS:
        return False
    if marked and found.get(MARK) != 1:
        return False
    if not marked and MARK in found:
        return False
    sizes = all(found[key] is None or type(found[key]) is int for key in ("dimensions", "size"))
    names = all(isinstance(found[key], str) for key in ("provider", "model", "setting"))
    return sizes and names and found["store"] == store


def is_any_record(found: Any, *, store: str) -> bool:
    return is_record(found, store=store, marked=True) or is_record(found, store=store, marked=False)


def refusal(store: str, setting: str, recorded: EmbeddingSpace, configured: EmbeddingSpace) -> str:
    embedding = f"{setting.rpartition('.')[0]}.embedding"
    return (
        f"{store} holds vectors of {recorded.describe()}; {embedding} names "
        f"{configured.describe()}. Vectors of two models never share a store: give {setting} "
        "another name, a separate index, or configure the embedding the store was made with. "
        "Nothing was changed: the store's vectors and the records they index stay."
    )


def not_a_record(name: str, store: str) -> str:
    return (
        f"{name} is named as the record of {store}'s embedding, but it is not a record: it is "
        "left as it is, and so is the store. Move it, or give the store another name"
    )


def claim(
    store: str,
    configured: EmbeddingSpace,
    *,
    label: str,
    setting: str,
    exists: Callable[[], bool],
    size: Callable[[], int | None],
    count: Callable[[], int],
    records: Callable[[], list[Mapping[str, Any]]],
    register: Callable[[dict[str, Any]], None],
    withdraw: Callable[[dict[str, Any]], None],
    ensure: Callable[[], None],
    client_path: str | None = None,
) -> None:
    """Open ``store`` for vectors of ``configured``: what is recorded, and the size of what is
    there, checked before anything changes; recorded if it was not; then ``ensure`` makes it or
    readies it.

    ``label`` is the store as messages name it; ``setting``, the setting it is named by, such as
    ``memory.vdb_config.collection_name``; ``client_path``, the directory its settings name, if
    any. The backend gives the store's operations: ``records`` raises ``EmbeddingSpaceError``
    for what is named as a record and is not one, ``register`` records a space without
    overwriting another's, and ``withdraw`` takes back what ``register`` made.
    """

    def check(found: list[Mapping[str, Any]]) -> None:
        for record in found:
            recorded = EmbeddingSpace.from_record(record)
            if not recorded.same(configured):
                raise EmbeddingSpaceError(refusal(label, setting, recorded, configured))

    # What is recorded, and the size of what is there, an empty store's too.
    found = records()
    check(found)
    held = size() if exists() else None
    if held is not None and configured.size is not None and held != configured.size:
        recorded = EmbeddingSpace.from_record(found[0]) if found else None
        made = EmbeddingSpace(
            recorded.provider if recorded else "unrecorded",
            recorded.model if recorded else "embedding",
            recorded.dimensions if recorded else None,
            held,
        )
        raise EmbeddingSpaceError(refusal(label, setting, made, configured))

    # Unrecorded: recorded now. Another Host may record another model meanwhile: whichever
    # then finds a record of another model takes its own back, so never two open the store.
    assumed = False
    if not found:
        assumed = held is not None and count() > 0
        mine = configured.record(
            store=store, setting=setting, assumed=assumed, client_path=client_path
        )
        register(mine)
        try:
            check(records())
        except EmbeddingSpaceError:
            withdraw(mine)
            raise

    # Made, or readied, as it is now: another Host of this model may have made it meanwhile.
    try:
        ensure()
    except Exception:
        if not exists():
            raise
        ensure()

    if assumed:
        logger.warning(
            "%s holds vectors made before stores were recorded: taken as %s, which cannot be "
            "verified",
            label,
            configured.describe(),
        )


def _at(settings: Mapping[str, Any], path: str) -> Any:
    for key in path.split("."):
        settings = settings.get(key) if isinstance(settings, Mapping) else None
    return settings


def recorded_conflicts(settings: Mapping[str, Any], defaults: Iterable[Path]) -> list[str]:
    """Each LanceDB store an Avatar's ``settings`` (its sections as plain data) open with
    another embedding than its record holds: what ``claim`` refuses at start, told from the
    records alone, before anything is installed.

    A record counts only for the store the settings open, as a runner chooses it: LanceDB, not
    a Qdrant server; its directory, the one ``client_path`` names or else the Avatar's own,
    under ``defaults``; its name. Nothing is opened, so neither LanceDB nor the model is needed;
    the model's size, unknown until it is asked, is not compared, and a remote store, such as
    Qdrant's, is checked only as it is opened.
    """
    from .config import vdb_backend

    roots = [Path(root).resolve() for root in defaults]

    def named(value: Any) -> Iterable[str]:
        # The directories the settings name a LanceDB store's in, beside its embedding.
        if isinstance(value, Mapping):
            if isinstance(value.get("client_path"), str) and "embedding" in value:
                yield value["client_path"]
            for item in value.values():
                yield from named(item)

    def opened(record: Mapping[str, Any], directory: Path) -> bool:
        # Whether the store the record describes is the one the settings open.
        setting = str(record["setting"])
        section = _at(settings, setting.partition(".vdb_config.")[0])
        if not isinstance(section, Mapping) or section.get("plugin") is None:
            return False  # No runner opens it.
        if section.get("enabled", True) is False:
            return False
        vdb = _at(settings, setting.rpartition(".")[0])
        try:
            if not isinstance(vdb, Mapping) or vdb_backend(dict(vdb)) != "lancedb":
                return False  # A Qdrant server's: not this table.
        except ValueError:
            return False
        if _at(settings, setting) != record["store"]:
            return False  # Configured to another store now.
        if client_path := vdb.get("client_path"):
            return directory == Path(client_path).expanduser().resolve()
        # The Avatar's own directory: recorded so, or found there by an earlier version's.
        inside = any(directory.is_relative_to(root) for root in roots)
        return inside and record.get("client_path") is None

    found, seen = [], set()
    directories = [*roots, *(Path(path).expanduser().resolve() for path in named(settings))]
    for directory in dict.fromkeys(directories):
        for path in sorted(directory.rglob("*.embedding.json")):
            if path in seen:
                continue  # A named directory inside the Avatar's own: one record, told once.
            seen.add(path)
            store = path.name.removesuffix(".embedding.json")
            try:
                record = json.loads(path.read_text("utf-8"))
            except (OSError, ValueError):
                continue  # Not one to tell from: start refuses it if its store is opened.
            if not is_any_record(record, store=store) or not opened(record, path.parent.resolve()):
                continue

            embedding = _at(settings, f"{str(record['setting']).rpartition('.')[0]}.embedding")
            if not isinstance(embedding, Mapping):
                continue
            recorded = EmbeddingSpace.from_record(record)
            configured = EmbeddingSpace.configured(embedding)
            if not recorded.same(configured):
                label = f"LanceDB table {store!r} in {path.parent}"
                found.append(refusal(label, str(record["setting"]), recorded, configured))
    return found
