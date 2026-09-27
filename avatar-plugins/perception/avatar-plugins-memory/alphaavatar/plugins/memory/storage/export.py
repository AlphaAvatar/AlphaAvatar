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

import asyncio
import pathlib

from alphaavatar.agents.memory.schemas import MemoryItem

from .graph import export_memory_graph
from .markdown import export_memory_items


class MemoryExportSink:
    def __init__(self, *, export_dir: pathlib.Path, graph_dir: pathlib.Path) -> None:
        self._export_dir = export_dir
        self._graph_dir = graph_dir

    async def __call__(self, items: list[MemoryItem]) -> None:
        if not items:
            return

        results = await asyncio.gather(
            asyncio.to_thread(export_memory_items, self._export_dir, items),
            asyncio.to_thread(export_memory_graph, self._graph_dir, items),
            return_exceptions=True,
        )
        errors = [result for result in results if isinstance(result, Exception)]
        if errors:
            raise ExceptionGroup("Memory export failed", errors)
