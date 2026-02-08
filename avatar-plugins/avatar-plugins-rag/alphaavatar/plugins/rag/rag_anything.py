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
import json
import os
import pathlib
from typing import Any, Literal

from lightrag import LightRAG
from lightrag.kg.shared_storage import initialize_pipeline_status
from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc
from livekit.agents import NOT_GIVEN, NotGivenOr, RunContext
from raganything import RAGAnything, RAGAnythingConfig

from alphaavatar.agents.tools import RAGBase
from alphaavatar.agents.utils import AsyncLoopThread, gpu_available

from .log import logger

RAG_INSTANCE = "rag_anything"
MAX_WORKERS = 4

DocParserType = Literal["mineru", "docling"]


async def _maybe_await(v):
    if inspect.isawaitable(v):
        return await v
    return v


class RAGAnythingTool(RAGBase):
    def __init__(
        self,
        *,
        working_dir: pathlib.Path,
        doc_parser: DocParserType = "mineru",
        openai_api_key: NotGivenOr[str] = NOT_GIVEN,
        openai_base_url: NotGivenOr[str] = NOT_GIVEN,
        **kwargs,
    ):
        super().__init__()

        if doc_parser == "mineru":
            if not gpu_available():
                logger.warning(
                    "[RAGAnythingTool] doc_parser='mineru' requested but no GPU detected. "
                    "Falling back to 'docling'."
                )
                self._doc_parser: DocParserType = "docling"
            else:
                logger.info("[RAGAnythingTool] Using 'mineru' parser with GPU support.")
                self._doc_parser = "mineru"
        else:
            self._doc_parser = doc_parser

        self._working_dir = working_dir / RAG_INSTANCE
        self._working_dir_index = self._working_dir / "index"
        self._working_dir_artifacts = self._working_dir / "artifacts"

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
        if os.path.exists(self._working_dir_index) and os.listdir(self._working_dir_index):
            logger.info("[RAGAnythingTool] ✅ Found existing LightRAG instance, loading...")
        else:
            logger.info(
                "[RAGAnythingTool] ❌ No existing LightRAG instance found, will create new one"
            )

        lightrag_instance = LightRAG(
            working_dir=self._working_dir_index,
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
            config=RAGAnythingConfig(
                working_dir=self._working_dir,
                parser=self._doc_parser,
            ),
            lightrag=lightrag_instance,
            vision_model_func=vision_model_func,
            # Note: working_dir, llm_model_func, embedding_func, etc. are inherited from lightrag_instance
        )

    def _require_ready(self) -> RAGAnything:
        if self._rag is None:
            raise RuntimeError("RAGAnythingTool not initialized")
        return self._rag

    def close(self):
        self._loop_thread.stop()

    async def query(
        self,
        *,
        query: str,
        ctx: RunContext | None = None,
        data_source: str = "all",
    ) -> str:
        if query is NOT_GIVEN:
            logger.warning("[RAGAnythingTool] Please provide valid query for [query] op!")
            return "Empty result because of invalid query"

        logger.info(f"[RAGAnythingTool] query func by query: {query}")

        rag = self._require_ready()
        result = await rag.aquery(query, mode="hybrid")
        return result

    async def indexing(
        self,
        *,
        file_paths_or_dir: list[str],
        ctx: RunContext | None = None,
        data_source: str = "all",
    ) -> str:
        rag = self._require_ready()
        message_logs = {}
        for file_path_or_dir in file_paths_or_dir:
            if os.path.isfile(file_path_or_dir):
                logger.info(
                    f"[RAGAnythingTool] Indexing func begin to process document [{file_path_or_dir}] ..."
                )
                await rag.process_document_complete(
                    file_path=file_path_or_dir, output_dir=str(self._working_dir_artifacts)
                )
                message_logs[file_path_or_dir] = (
                    f"Indexed document [{file_path_or_dir}] successfully."
                )
            elif os.path.isdir(file_path_or_dir):
                logger.info(
                    f"[RAGAnythingTool] Indexing func begin to process folder [{file_path_or_dir}] ..."
                )
                await rag.process_folder_complete(
                    folder_path=file_path_or_dir,
                    output_dir=str(self._working_dir_artifacts),
                    file_extensions=[".pdf", ".docx", ".pptx"],
                    recursive=True,
                    max_workers=MAX_WORKERS,
                )
                message_logs[file_path_or_dir] = (
                    f"Indexed folder [{file_path_or_dir}] successfully."
                )
            else:
                logger.warning(
                    f"[RAGAnythingTool] Indexing func found invalid path [{file_path_or_dir}], skipped."
                )
                message_logs[file_path_or_dir] = (
                    f"Indexing func found invalid path [{file_path_or_dir}], skipped."
                )

        return json.dumps(message_logs, ensure_ascii=False, indent=2)
