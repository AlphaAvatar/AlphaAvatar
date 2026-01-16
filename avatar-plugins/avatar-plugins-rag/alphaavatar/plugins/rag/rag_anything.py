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
import inspect
import os
import pathlib
from typing import Any

from lightrag import LightRAG
from lightrag.kg.shared_storage import initialize_pipeline_status
from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc
from livekit.agents import NOT_GIVEN, NotGivenOr, RunContext
from raganything import RAGAnything

from alphaavatar.agents.tools import RAGBase
from alphaavatar.agents.utils.loop_thread import AsyncLoopThread

from .log import logger


RAG_INSTANCE = "rag_anything"
MAX_WORKERS = 4


async def _maybe_await(v):
    if inspect.isawaitable(v):
        return await v
    return v


class RAGAnythingTool(RAGBase):
    def __init__(
        self,
        *args,
        working_dir: pathlib.Path,
        openai_api_key: NotGivenOr[str] = NOT_GIVEN,
        openai_base_url: NotGivenOr[str] = NOT_GIVEN,
        **kwargs,
    ):
        super().__init__()

        self._working_dir = working_dir / RAG_INSTANCE
        self._openai_api_key = openai_api_key or (os.getenv("OPENAI_API_KEY") or NOT_GIVEN)
        self._openai_base_url = openai_base_url or (os.getenv("OPENAI_BASE_URL") or NOT_GIVEN)

        self._rag: RAGAnything | None = None
        self._loop_thread = AsyncLoopThread(name="raganything-loop")
        self._loop_thread.submit(self._load_instance())

    async def _load_instance(self) -> None:

        async def llm_model_func(
            prompt: str,
            system_prompt: str | None = None,
            history_messages: list[dict[str, Any]] | None = None,
            **kwargs,
        ):
            return await _maybe_await(
                openai_complete_if_cache(
                    "gpt-4o-mini",
                    prompt,
                    system_prompt=system_prompt,
                    history_messages=history_messages or [],
                    api_key=self._openai_api_key,
                    base_url=self._openai_base_url,
                    **kwargs,
                )
            )

        async def embedding_func(texts: list[str]):
            return await _maybe_await(
                openai_embed(
                    texts,
                    model="text-embedding-3-large",
                    api_key=self._openai_api_key,
                    base_url=self._openai_base_url,
                )
            )

        # Create/load LightRAG instance with your configuration
        if os.path.exists(self._working_dir) and os.listdir(self._working_dir):
            logger.info("[RAGAnythingTool] ✅ Found existing LightRAG instance, loading...")
        else:
            logger.info("[RAGAnythingTool] ❌ No existing LightRAG instance found, will create new one")

        lightrag_instance = LightRAG(
            working_dir=self._working_dir,
            llm_model_func=llm_model_func,
            embedding_func=EmbeddingFunc(
                embedding_dim=3072,
                max_token_size=8192,
                func=embedding_func,
            ),
        )

        # Initialize storage (this will load existing data if available)
        await lightrag_instance.initialize_storages()
        await initialize_pipeline_status()

        # Define vision model function for image processing
        async def vision_model_func(
            prompt: str,
            system_prompt: str | None = None,
            history_messages: list[dict[str, Any]] | None = None,
            image_data: str | None = None,
            messages: list[dict[str, Any]] | None = None,
            **kwargs,
        ):
            # If messages format is provided (for multimodal VLM enhanced query), use it directly
            if messages:
                return await _maybe_await(
                    openai_complete_if_cache(
                        "gpt-4o",
                        "",
                        messages=messages,
                        api_key=self._openai_api_key,
                        base_url=self._openai_base_url,
                        **kwargs,
                    )
                )

            # Traditional single image format
            if image_data:
                mm_messages = []
                if system_prompt:
                    mm_messages.append({"role": "system", "content": system_prompt})
                mm_messages.append(
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
                return await _maybe_await(
                    openai_complete_if_cache(
                        "gpt-4o",
                        "",
                        messages=mm_messages,
                        api_key=self._openai_api_key,
                        base_url=self._openai_base_url,
                        **kwargs,
                    )
                )

            # Pure text format
            return await llm_model_func(
                prompt, system_prompt=system_prompt, history_messages=history_messages
            )

        # Now use existing LightRAG instance to initialize RAGAnything
        self._rag = RAGAnything(
            lightrag=lightrag_instance,
            vision_model_func=vision_model_func,
        )

    def _require_ready(self) -> RAGAnything:
        if self._rag is None:
            raise RuntimeError("RAGAnythingTool not initialized")
        return self._rag

    def close(self):
        self._loop_thread.stop()

    async def query(
        self,
        ctx: RunContext,
        data_source: str = "all",
        query: NotGivenOr[str] = NOT_GIVEN,
    ) -> str:
        if query is NOT_GIVEN:
            logger.warning("[RAGAnythingTool] Please provide valid query for [query] op!")
            return "Empty result because of invalid query"

        result = await self._rag.aquery(
            query,
            mode="hybrid"
        )
        return result

    async def indexing(
        self,
        ctx: RunContext,
        data_source: str = "all",
        file_path_or_dir: NotGivenOr[str] = NOT_GIVEN,
    ) -> Any:
        if os.path.isfile(file_path_or_dir):
            logger.info("[RAGAnythingTool] Begin to process document...")
            await self._rag.process_document_complete(
                file_path=file_path_or_dir,
                output_dir="./output"
            )
        elif os.path.isdir(file_path_or_dir):
            logger.info("[RAGAnythingTool] Begin to process folder...")
            await self._rag.process_folder_complete(
                folder_path=file_path_or_dir,
                output_dir="./output",
                file_extensions=[".pdf", ".docx", ".pptx"],
                recursive=True,
                max_workers=MAX_WORKERS
            )
