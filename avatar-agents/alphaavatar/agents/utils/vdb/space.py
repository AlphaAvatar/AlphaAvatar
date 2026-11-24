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
refused and left as it is.

Hosts sharing a store record it at once safely. A record is decided or pending: a Host relies
only on a decided one, which is never taken back, and opens the store beside one of its model
without recording anything. Finding none, it records its own pending and reads again: finding a
decided one now, it takes its own back and goes on as beside that one; finding none, it decides
its own only if nothing of another model, pending or decided, is recorded, else takes it back
and refuses. A Host deciding its own wrote it before reading, and keeps it: of two Hosts
deciding records of two models, each would have read the other's. So whatever the order, every
decided record, and every Host that opened the store, is of one model. A store recording one
record only, placed once and never taken back (LanceDB's file), has it decided as placed.

A store made before stores were recorded is taken as the configured space only while its
vectors are of the configured size, recorded then as assumed if it holds any: what model made
them cannot be told.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from alphaavatar.agents.workspace import WorkspacePaths

logger = logging.getLogger(__name__)

MARK = "alphaavatar.embedding_space"  # A record's own field: the version of its layout.
PENDING = "pending"  # True while its Host has not decided it: never relied on by another.
_FIELDS = frozenset({"provider", "model", "dimensions", "size", "store", "setting"})
# ``client_path``: in records a9b2081a wrote, read and never written now.
_OPTIONAL = frozenset({MARK, PENDING, "assumed", "client_path"})


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

    def record(self, *, store: str, setting: str, assumed: bool = False) -> dict[str, Any]:
        """What is kept beside the store, decided: the space, the store, and the setting that
        names it."""
        found = {
            MARK: 1,
            "provider": self.provider,
            "model": self.model,
            "dimensions": self.dimensions,
            "size": self.size,
            "store": store,
            "setting": setting,
        }
        return found | ({"assumed": True} if assumed else {})


def is_record(found: Any, *, store: str, marked: bool) -> bool:
    """Whether ``found`` is a record of ``store``: a record's fields and nothing else, with its
    mark (``marked``) or, as the version before marks wrote one, without."""
    if not isinstance(found, Mapping) or set(found) - _OPTIONAL != _FIELDS:
        return False
    if marked and found.get(MARK) != 1:
        return False
    if not marked and (MARK in found or PENDING in found):
        return False
    if PENDING in found and found[PENDING] is not True:
        return False
    sizes = all(found[key] is None or type(found[key]) is int for key in ("dimensions", "size"))
    names = all(isinstance(found[key], str) for key in ("provider", "model", "setting"))
    return sizes and names and found["store"] == store


def is_any_record(found: Any, *, store: str) -> bool:
    return is_record(found, store=store, marked=True) or is_record(found, store=store, marked=False)


def refusal(
    store: str,
    setting: str,
    recorded: EmbeddingSpace,
    configured: EmbeddingSpace,
    *,
    pending: bool = False,
) -> str:
    embedding = f"{setting.rpartition('.')[0]}.embedding"
    held = (
        f"is being recorded for vectors of {recorded.describe()} by another Host, or was left "
        "so by one stopped while recording it"
        if pending
        else f"holds vectors of {recorded.describe()}"
    )
    return (
        f"{store} {held}; {embedding} names "
        f"{configured.describe()}. Vectors of two models never share a store: give {setting} "
        "another name, a separate index, or configure the embedding the store was made with. "
        "Nothing was changed: the store's vectors and the records they index stay."
    )


def not_a_record(name: str, store: str) -> str:
    return (
        f"{name} is named as the record of {store}'s embedding, but it is not a record: it is "
        "left as it is, and so is the store. Move it, or give the store another name"
    )


def _decided(found: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [record for record in found if not record.get(PENDING)]


def _withdraw(withdraw: Callable[[dict[str, Any]], None], mine: dict[str, Any], label: str) -> None:
    try:
        withdraw(mine)
    except Exception as error:
        # Left pending: no Host relies on it, and another model is refused beside it.
        logger.warning("%s: its pending record could not be taken back: %s", label, error)


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
    confirm: Callable[[dict[str, Any]], None],
    withdraw: Callable[[dict[str, Any]], None],
    ensure: Callable[[], None],
) -> None:
    """Open ``store`` for vectors of ``configured``: what is recorded, and the size of what is
    there, checked before anything changes; recorded and decided if nothing was; then
    ``ensure`` makes it or readies it.

    ``label`` is the store as messages name it; ``setting``, the setting it is named by, such as
    ``memory.vdb_config.collection_name``. The backend gives the store's operations:
    ``records`` lists every record, pending ones too, raising ``EmbeddingSpaceError`` for what
    is named as a record and is not one; ``register`` records ``mine`` without overwriting
    another's, pending unless the store records one record only, placed once (then decided as
    placed, or not at all where another's is); ``confirm`` decides a pending one, and
    ``withdraw`` takes back one ``register`` made while it is pending.
    """

    def check(found: list[Mapping[str, Any]]) -> None:
        for record in found:
            recorded = EmbeddingSpace.from_record(record)
            if not recorded.same(configured):
                pending = bool(record.get(PENDING))
                raise EmbeddingSpaceError(
                    refusal(label, setting, recorded, configured, pending=pending)
                )

    # What is decided, and the size of what is there, an empty store's too.
    found = records()
    check(_decided(found))
    held = size() if exists() else None
    if held is not None and configured.size is not None and held != configured.size:
        recorded = EmbeddingSpace.from_record(_decided(found)[0]) if _decided(found) else None
        made = EmbeddingSpace(
            recorded.provider if recorded else "unrecorded",
            recorded.model if recorded else "embedding",
            recorded.dimensions if recorded else None,
            held,
        )
        raise EmbeddingSpaceError(refusal(label, setting, made, configured))

    # Nothing decided: its own recorded, read again, then decided only if nothing of another
    # model is recorded; taken back on refusal or on any failure before it is decided.
    assumed = False
    if not _decided(found):
        assumed = held is not None and count() > 0
        mine = configured.record(store=store, setting=setting, assumed=assumed)
        register(mine)
        try:
            found = records()
            if _decided(found):
                check(_decided(found))  # Decided meanwhile, by another Host or as placed.
                withdraw(mine)  # A decided record of its model holds the store: its own not needed.
            else:
                check(found)
                confirm(mine)
        except BaseException:
            _withdraw(withdraw, mine, label)
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


def recorded_conflicts(
    settings: Mapping[str, Any], workspace: WorkspacePaths, modules: Mapping[str, Mapping[str, str]]
) -> list[str]:
    """Each LanceDB store an Avatar's ``settings`` (its sections as plain data) open with
    another embedding than its record holds: what ``claim`` refuses at start, told from the
    records alone, before anything is installed.

    Each store is found as its runner finds it: in each section selecting a plugin and naming
    LanceDB, the directory ``lancedb_directory`` gives for the Avatar's ``workspace`` and the
    plugin's storage namespace, from the module its entry point names in ``modules`` (by
    capability type, which is the section's path, and name, as a build's catalog records them);
    there, the record of each table a setting of the section names. Nothing is opened, so
    neither LanceDB nor the model is needed: the model's size, unknown until it is asked, is not
    compared; a remote store, such as Qdrant's, and a plugin the catalog does not name are
    checked only as they are opened.
    """
    from alphaavatar.agents.runtime.plugin.schemas.resolved_plugin import ResolvedPlugin

    from .config import lancedb_directory, vdb_backend

    def sections(value: Any, path: tuple[str, ...] = ()):
        # Each section selecting a plugin beside its store settings, by its path: tools.mcp.
        if isinstance(value, Mapping):
            if "plugin" in value and isinstance(value.get("vdb_config"), Mapping):
                yield ".".join(path), value
            for key, item in value.items():
                yield from sections(item, (*path, str(key)))

    found = []
    for path, section in sections(settings):
        vdb, plugin = section["vdb_config"], section.get("plugin")
        module = (modules.get(path) or {}).get(plugin) if isinstance(plugin, str) else None
        embedding = vdb.get("embedding")
        if module is None or section.get("enabled", True) is False:
            continue  # No plugin the build installs opens it.
        try:
            if vdb_backend(dict(vdb)) != "lancedb" or not isinstance(embedding, Mapping):
                continue  # A Qdrant server's.
        except ValueError:
            continue

        directory = lancedb_directory(vdb, workspace, ResolvedPlugin.namespace_of(module))
        for item in sorted(directory.glob("*.embedding.json")):
            store = item.name.removesuffix(".embedding.json")
            try:
                record = json.loads(item.read_text("utf-8"))
            except (OSError, ValueError):
                continue  # Not one to tell from: start refuses it if its store is opened.
            if not is_any_record(record, store=store):
                continue
            owner, _, key = str(record["setting"]).rpartition(".")
            if owner != f"{path}.vdb_config" or vdb.get(key) != store:
                continue  # Not a table this section's settings name now.

            recorded = EmbeddingSpace.from_record(record)
            configured = EmbeddingSpace.configured(embedding)
            if not recorded.same(configured):
                label = f"LanceDB table {store!r} in {directory}"
                found.append(refusal(label, str(record["setting"]), recorded, configured))
    return found
