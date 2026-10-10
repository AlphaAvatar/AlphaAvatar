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

from typing import TYPE_CHECKING, Any

from alphaavatar.agents.runtime.capability import avatar_capability
from alphaavatar.agents.tools import ToolBase

from .enums import RAGOp
from .schemas import RAGRequest

if TYPE_CHECKING:
    from alphaavatar.agents.runtime import AvatarRuntime


DESCRIPTION = """Retrieve and index user-provided or locally stored documents.
Use op=query with query to retrieve grounded results from an existing knowledge base.
Use op=indexing with file_paths_or_dir only when the user has authorized storing those documents.
Indexing changes the persistent index; a lookup request alone does not authorize indexing.
The current backend supports data_source=all only; named corpora are not yet implemented.
Use public-web search for public information not contained in the user's documents.
""".strip()


@avatar_capability(name="RAG", description=DESCRIPTION, input_schema=RAGRequest)
class RAGService(ToolBase):
    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        init_config: dict[str, Any],
    ) -> None:
        super().__init__(runtime=runtime)
        self._options = dict(init_config)
        self._service = None

    async def _start(self) -> None:
        from .rag_anything import RAGAnythingTool

        path = self._runtime.session.session_path
        if path is None:
            raise RuntimeError("Session workspace must exist before tools start")
        self._service = RAGAnythingTool(session_path=path, **self._options)

    async def _invoke(self, request: RAGRequest) -> Any:
        if request.op == RAGOp.QUERY:
            return await self._service.query(query=request.query, data_source=request.data_source)

        return await self._service.indexing(
            file_paths_or_dir=request.file_paths_or_dir,
            data_source=request.data_source,
        )

    async def _stop(self) -> None:
        if self._service is not None:
            await self._service.aclose()
            self._service = None
