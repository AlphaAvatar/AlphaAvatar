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
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from alphaavatar.agents.avatar.provider.schemas import ModelTextPart
from alphaavatar.agents.runtime.capability.result import CapabilityResult
from alphaavatar.agents.tools.schemas import ToolError
from alphaavatar.core.cleanup import wait_for_cleanup

if TYPE_CHECKING:
    from alphaavatar.agents.utils.files.work_dirs import SessionPath


class RAGAnythingTool:
    """One event-loop owner for initialization, queries, indexing and storage finalization."""

    def __init__(
        self,
        *,
        session_path: SessionPath,
        doc_parser: Literal["mineru", "docling"] = "mineru",
        openai_api_key: str | None = None,
        openai_base_url: str | None = None,
    ) -> None:
        if doc_parser not in {"mineru", "docling"}:
            raise ValueError("Unknown document parser")
        self.session_path = session_path
        self._parser = doc_parser
        self._key = openai_api_key or os.getenv("OPENAI_API_KEY")
        self._base_url = openai_base_url or os.getenv("OPENAI_BASE_URL")
        self._load_task: asyncio.Task[Any] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._lightrag = None
        self._operation_lock = asyncio.Lock()

    @staticmethod
    def _dependencies():
        from lightrag import LightRAG
        from lightrag.kg.shared_storage import initialize_pipeline_status
        from lightrag.llm.openai import openai_complete_if_cache, openai_embed
        from lightrag.utils import EmbeddingFunc
        from raganything import RAGAnything, RAGAnythingConfig

        return (
            LightRAG,
            initialize_pipeline_status,
            openai_complete_if_cache,
            openai_embed,
            EmbeddingFunc,
            RAGAnything,
            RAGAnythingConfig,
        )

    @staticmethod
    def _observe(task: asyncio.Task[Any]) -> None:
        if not task.cancelled():
            task.exception()

    @staticmethod
    def _validate_source(data_source: str) -> None:
        if data_source != "all":
            raise ToolError("This RAG backend currently exposes only data_source='all'")

    def _paths(self) -> tuple[Path, Path, Path]:
        root = self.session_path.artifacts_dir / "rag_anything"
        index, artifacts = root / "index", root / "artifacts"
        index.mkdir(parents=True, exist_ok=True)
        artifacts.mkdir(parents=True, exist_ok=True)
        return root, index, artifacts

    async def _load(self):
        (
            LightRAG,
            initialize_pipeline_status,
            complete,
            embed,
            EmbeddingFunc,
            RAGAnything,
            RAGAnythingConfig,
        ) = await asyncio.to_thread(self._dependencies)
        root, index, _ = await asyncio.to_thread(self._paths)
        parser = self._parser
        if parser == "mineru":
            from alphaavatar.agents.utils import gpu_available

            if not await asyncio.to_thread(gpu_available):
                parser = "docling"
        options = {}
        if self._key is not None:
            options["api_key"] = self._key
        if self._base_url is not None:
            options["base_url"] = self._base_url

        async def llm(prompt, system_prompt=None, history_messages=None, **kwargs):
            return await complete(
                "gpt-4o-mini",
                prompt,
                system_prompt=system_prompt,
                history_messages=history_messages or [],
                **options,
                **kwargs,
            )

        async def embedding(texts):
            return await embed(texts, model="text-embedding-3-large", **options)

        async def vision(
            prompt,
            system_prompt=None,
            history_messages=None,
            image_data=None,
            messages=None,
            **kwargs,
        ):
            if messages:
                return await complete("gpt-4o", "", messages=messages, **options, **kwargs)
            if image_data:
                parts = []
                if system_prompt:
                    parts.append({"role": "system", "content": system_prompt})
                parts.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{image_data}"},
                            },
                        ],
                    }
                )
                return await complete("gpt-4o", "", messages=parts, **options, **kwargs)
            return await llm(prompt, system_prompt, history_messages, **kwargs)

        # Preserve the existing backend model and index settings; no change to stored embeddings.
        self._lightrag = LightRAG(
            working_dir=index,
            llm_model_func=llm,
            embedding_func=EmbeddingFunc(embedding_dim=3072, max_token_size=8192, func=embedding),
        )
        await self._lightrag.initialize_storages()
        await initialize_pipeline_status()
        return RAGAnything(
            config=RAGAnythingConfig(working_dir=root, parser=parser),
            lightrag=self._lightrag,
            vision_model_func=vision,
        )

    async def _ensure_loaded(self):
        if self._close_task is not None:
            raise RuntimeError("RAG service is closed")
        if self._load_task is None:
            self._load_task = asyncio.create_task(self._load(), name="rag_load")
            self._load_task.add_done_callback(self._observe)
        # A cancelled query does not cancel shared initialization or create a second event loop.
        result = await asyncio.shield(self._load_task)
        if self._close_task is not None:
            raise RuntimeError("RAG service closed during initialization")
        return result

    async def query(self, *, query: str, data_source: str = "all") -> str:
        self._validate_source(data_source)
        rag = await self._ensure_loaded()
        async with self._operation_lock:
            result = await rag.aquery(query, mode="hybrid")
        if not result:
            return "No relevant result was found in the session knowledge base."
        return str(result)

    async def indexing(
        self, *, file_paths_or_dir: list[str], data_source: str = "all"
    ) -> CapabilityResult:
        self._validate_source(data_source)
        if not file_paths_or_dir:
            raise ToolError("RAG indexing requires at least one path")
        rag = await self._ensure_loaded()
        _, _, artifacts = await asyncio.to_thread(self._paths)
        results = {}
        failed = False
        async with self._operation_lock:
            for value in file_paths_or_dir:
                path = Path(value)
                is_file, is_dir = await asyncio.to_thread(lambda p=path: (p.is_file(), p.is_dir()))
                if is_file:
                    await rag.process_document_complete(file_path=value, output_dir=str(artifacts))
                    results[value] = "Indexed document successfully."
                elif is_dir:
                    await rag.process_folder_complete(
                        folder_path=value,
                        output_dir=str(artifacts),
                        recursive=True,
                        file_extensions=[".pdf", ".docx", ".pptx"],
                        max_workers=4,
                    )
                    results[value] = "Indexed folder successfully."
                else:
                    results[value] = "Skipped: path is missing or is not a regular file/directory."
                    failed = True
        return CapabilityResult(
            parts=(ModelTextPart(json.dumps(results, ensure_ascii=False, indent=2)),),
            is_error=failed,
        )

    async def _close(self) -> None:
        if self._load_task is not None:
            await asyncio.gather(self._load_task, return_exceptions=True)
        if self._lightrag is not None:
            await self._lightrag.finalize_storages()
            self._lightrag = None

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="rag_close")
        await wait_for_cleanup(self._close_task)
