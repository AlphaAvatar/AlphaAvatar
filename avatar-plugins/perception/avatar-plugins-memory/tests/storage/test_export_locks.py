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
"""Memory Markdown and graph exports through the shared directory lock, offline."""

from __future__ import annotations

import asyncio
import errno
import json
from pathlib import Path

import pytest
from lock_holder import HANG_GUARD, held_elsewhere

from alphaavatar.agents.memory.enums import MemoryType
from alphaavatar.agents.memory.schemas import (
    MemoryContextRef,
    MemoryItem,
    MemoryOwnerRef,
    MemoryScope,
)
from alphaavatar.plugins.memory.storage.export import MemoryExportSink
from alphaavatar.plugins.memory.storage.graph import export_memory_graph
from alphaavatar.plugins.memory.storage.markdown import export_memory_items

EXPORTS = {"markdown": export_memory_items, "graph": export_memory_graph}


def items(*values: str) -> list[MemoryItem]:
    context = MemoryContextRef(episode_id="episode", context_id="context", session_id="session")
    return [
        MemoryItem(
            context=context,
            scope=MemoryScope.context("context"),
            owner_refs=[MemoryOwnerRef.avatar("avatar")],
            value=value,
            memory_type=MemoryType.ENV,
        )
        for value in values
    ]


def contents(root: Path) -> dict[str, bytes | None]:
    """Every path under root with its bytes; None marks a directory or a link."""
    return {
        str(path.relative_to(root)): None
        if path.is_symlink() or path.is_dir()
        else path.read_bytes()
        for path in root.rglob("*")
    }


def exported(directory: Path) -> list[str]:
    return sorted(
        str(path.relative_to(directory))
        for path in directory.rglob("*")
        if path.is_file() and path.name != ".write.lock"
    )


@pytest.mark.parametrize("kind", EXPORTS)
def test_each_export_writes_under_the_lock_and_keeps_its_file(kind: str, tmp_path: Path) -> None:
    directory = tmp_path / kind
    EXPORTS[kind](directory, items("lamp turned on"))
    EXPORTS[kind](directory, items("door opened"))  # The lock is free again after each run.
    lock = directory / ".write.lock"
    assert lock.is_file() and not lock.is_symlink()
    expected = {"markdown": 2, "graph": 3}[kind]  # Two documents, or three JSONL files.
    assert len(exported(directory)) == expected


@pytest.mark.parametrize("kind", EXPORTS)
def test_a_linked_lock_stops_an_export_before_any_protected_write(
    kind: str, tmp_path: Path
) -> None:
    directory, outside = tmp_path / kind, tmp_path / "outside.txt"
    directory.mkdir()
    outside.write_text("keep me\n")
    if kind == "graph":
        (directory / "memories.jsonl").write_text('{"memory_id": "kept", "revision": 1}\n')
    (directory / ".write.lock").symlink_to(outside)
    before = contents(tmp_path)

    with pytest.raises(OSError) as refused:
        EXPORTS[kind](directory, items("lamp turned on"))
    assert refused.value.errno == errno.ELOOP
    # The link, its target and every existing export stay; nothing new was written.
    assert contents(tmp_path) == before
    assert outside.read_text() == "keep me\n"


async def test_the_export_sink_reports_both_refusals(tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("keep me\n")
    directories = {kind: tmp_path / kind for kind in EXPORTS}
    for directory in directories.values():
        directory.mkdir()
        (directory / ".write.lock").symlink_to(outside)
    sink = MemoryExportSink(export_dir=directories["markdown"], graph_dir=directories["graph"])
    with pytest.raises(ExceptionGroup) as failed:
        await sink(items("lamp turned on"))
    assert [error.errno for error in failed.value.exceptions] == [errno.ELOOP, errno.ELOOP]
    assert outside.read_text() == "keep me\n"
    assert all(exported(directory) == [] for directory in directories.values())


def test_a_failed_graph_export_releases_its_lock(tmp_path: Path) -> None:
    directory = tmp_path / "graph"
    directory.mkdir()
    records = directory / "memories.jsonl"
    records.write_text("not json\n")
    with pytest.raises(RuntimeError, match="Invalid graph JSONL"):
        export_memory_graph(directory, items("lamp turned on"))
    records.unlink()
    # A leaked lock would make this wait out the lock timeout and fail.
    export_memory_graph(directory, items("lamp turned on"))
    assert [json.loads(line)["revision"] for line in records.read_text().splitlines()] == [1]


async def test_a_cancelled_export_finishes_under_another_processs_lock_then_releases_it(
    tmp_path: Path,
) -> None:
    markdown, graph = tmp_path / "markdown", tmp_path / "graph"
    sink = MemoryExportSink(export_dir=markdown, graph_dir=graph)
    with held_elsewhere(markdown, tmp_path) as release:
        task = asyncio.create_task(sink(items("lamp turned on")))
        # The graph export has finished, so the Markdown export started beside it.
        async with asyncio.timeout(HANG_GUARD):
            while not (graph / "links.jsonl").exists():
                await asyncio.sleep(0.005)
        assert exported(markdown) == []  # The other process still holds the lock.
        task.cancel()
        release.touch()
        with pytest.raises(asyncio.CancelledError):
            async with asyncio.timeout(HANG_GUARD):
                await task
    # The cancelled caller waited for the owned write, which ran once the lock was free.
    assert len(exported(markdown)) == 1
    await sink(items("door opened"))
    assert len(exported(markdown)) == 2 and (markdown / ".write.lock").is_file()
