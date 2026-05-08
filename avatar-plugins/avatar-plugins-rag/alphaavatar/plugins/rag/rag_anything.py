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
import asyncio
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
from alphaavatar.agents.utils.files.work_dirs import UserPath, UserPathSnapshot

from .log import logger

RAG_INSTANCE = "rag_anything"
MAX_WORKERS = 4

DocParserType = Literal["mineru", "docling"]


async def _maybe_await(v):
    if inspect.isawaitable(v):
        return await v
    return v


class RAGSlot:
    def __init__(
        self,
        *,
        rag: RAGAnything,
        user_id: str,
        working_dir: pathlib.Path,
        index_dir: pathlib.Path,
        artifacts_dir: pathlib.Path,
    ) -> None:
        self.rag = rag
        self.user_id = user_id
        self.working_dir = working_dir
        self.index_dir = index_dir
        self.artifacts_dir = artifacts_dir


class RAGAnythingTool(RAGBase):
    def __init__(
        self,
        *,
        user_path: UserPath,
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

        self._user_path = user_path
        self._user_path_unsubscribe = self._user_path.subscribe(self._on_user_path_changed)

        self._openai_api_key = openai_api_key or (os.getenv("OPENAI_API_KEY") or NOT_GIVEN)
        self._openai_base_url = openai_base_url or (os.getenv("OPENAI_BASE_URL") or NOT_GIVEN)

        self._rag: RAGAnything | None = None
        self._previous_rags: list[RAGSlot] = []

        self._load_future = None
        self._load_error: Exception | None = None

        self._loop_thread = AsyncLoopThread(name="raganything-loop")

        try:
            self._load_future = self._loop_thread.submit(self._load_instance())
        except Exception as e:
            self._load_error = e
            logger.warning("[RAGAnythingTool] Background load submit failed: %s", e)

    @property
    def working_dir(self) -> pathlib.Path:
        _, working_dir, _, _ = self._current_rag_paths()
        return working_dir

    @property
    def working_dir_index(self) -> pathlib.Path:
        _, _, index_dir, _ = self._current_rag_paths()
        return index_dir

    @property
    def working_dir_artifacts(self) -> pathlib.Path:
        _, _, _, artifacts_dir = self._current_rag_paths()
        return artifacts_dir

    def _current_rag_paths(self) -> tuple[str, pathlib.Path, pathlib.Path, pathlib.Path]:
        user_id = self._user_path.user_id

        working_dir = self._user_path.data_dir / RAG_INSTANCE
        index_dir = working_dir / "index"
        artifacts_dir = working_dir / "artifacts"

        working_dir.mkdir(parents=True, exist_ok=True)
        index_dir.mkdir(parents=True, exist_ok=True)
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        return user_id, working_dir, index_dir, artifacts_dir

    async def _load_instance(self) -> RAGAnything:
        user_id, working_dir, index_dir, artifacts_dir = self._current_rag_paths()

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
        if os.path.exists(index_dir) and os.listdir(index_dir):
            logger.info("[RAGAnythingTool] ✅ Found existing LightRAG instance, loading...")
        else:
            logger.info(
                "[RAGAnythingTool] ❌ No existing LightRAG instance found, will create new one"
            )

        lightrag_instance = LightRAG(
            working_dir=index_dir,
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
        rag = RAGAnything(
            config=RAGAnythingConfig(
                working_dir=working_dir,
                parser=self._doc_parser,
            ),
            lightrag=lightrag_instance,
            vision_model_func=vision_model_func,
        )

        self._rag = rag

        logger.info(
            "[RAGAnythingTool] RAGAnything instance loaded user_id=%s working_dir=%s",
            user_id,
            working_dir,
        )

        return rag

    async def _await_thread_future(self, future):
        if future is None:
            return None

        if inspect.isawaitable(future):
            return await future

        return await asyncio.wrap_future(future)

    async def _ensure_loaded(self) -> RAGAnything:
        """
        Wait for background initialization if it is still running.
        If background initialization was not submitted or failed, initialize inline.
        """
        if self._rag is not None:
            return self._rag

        if self._load_future is not None:
            try:
                await self._await_thread_future(self._load_future)
            except Exception as e:
                self._load_error = e
                self._load_future = None
                logger.exception("[RAGAnythingTool] Background RAG load failed")
                raise RuntimeError(f"RAGAnything instance failed to initialize: {e}") from e

            if self._rag is not None:
                return self._rag

        try:
            await self._load_instance()
        except Exception as e:
            self._load_error = e
            logger.exception("[RAGAnythingTool] Failed to initialize RAGAnything instance")
            raise RuntimeError(f"RAGAnything instance failed to initialize: {e}") from e

        if self._rag is None:
            raise RuntimeError("RAGAnything instance initialization completed but _rag is None.")

        return self._rag

    def _on_user_path_changed(
        self,
        user_path: UserPath,
        old_path: UserPathSnapshot,
        new_path: UserPathSnapshot,
    ) -> None:
        logger.info(
            "[RAGAnythingTool] User path changed: %s -> %s",
            old_path.user_root,
            new_path.user_root,
        )

        if self._rag is not None:
            old_working_dir = old_path.data_dir / RAG_INSTANCE
            old_index_dir = old_working_dir / "index"
            old_artifacts_dir = old_working_dir / "artifacts"

            self._previous_rags.append(
                RAGSlot(
                    rag=self._rag,
                    user_id=old_path.user_id,
                    working_dir=old_working_dir,
                    index_dir=old_index_dir,
                    artifacts_dir=old_artifacts_dir,
                )
            )

        self._rag = None
        self._load_error = None
        self._load_future = None

        try:
            self._load_future = self._loop_thread.submit(self._load_instance())
        except Exception as e:
            self._load_error = e
            logger.warning(
                "[RAGAnythingTool] Failed to submit reload after user path change: %s", e
            )

    async def query(
        self,
        *,
        query: str,
        ctx: RunContext | None = None,
        data_source: str = "all",
    ) -> str:
        if query is NOT_GIVEN:
            logger.warning("[RAGAnythingTool] Please provide valid query for [query] op!")
            return "Empty result because of invalid query."

        logger.info(f"[RAGAnythingTool] query func by query: {query}")

        current_rag = await self._ensure_loaded()

        sections: list[str] = []
        errors: list[str] = []

        try:
            current_result = await current_rag.aquery(query, mode="hybrid")
            if current_result:
                sections.append(
                    "## Current user knowledge base\n"
                    "This result comes from the currently resolved user workspace. "
                    "Prefer it over temporary session results if there is any conflict.\n\n"
                    f"{current_result}"
                )
        except Exception as e:
            logger.warning("[RAGAnythingTool] current RAG query failed: %s", e)
            errors.append(f"- Current user knowledge base query failed: {e}")

        for idx, slot in enumerate(self._previous_rags):
            try:
                previous_result = await slot.rag.aquery(query, mode="hybrid")
                if previous_result:
                    sections.append(
                        f"## Temporary session knowledge base {idx + 1}\n"
                        "This result comes from a temporary workspace created before the "
                        "user identity was resolved. Treat it as relevant to the current "
                        "conversation, but lower priority than the current user workspace.\n\n"
                        f"{previous_result}"
                    )
            except Exception as e:
                logger.warning(
                    "[RAGAnythingTool] previous RAG query failed user_id=%s error=%s",
                    slot.user_id,
                    e,
                )
                errors.append(
                    f"- Temporary session knowledge base query failed for user_id={slot.user_id}: {e}"
                )

        if not sections and not errors:
            return (
                "No relevant result was found in the current user knowledge base "
                "or temporary session knowledge base."
            )

        output_parts: list[str] = [
            "# RAG Query Results",
            "",
            f"Query: {query}",
            "",
            "Use these results as supporting context. Prefer the current user knowledge base "
            "when it conflicts with temporary session results.",
            "",
        ]

        output_parts.extend(sections)

        if errors:
            output_parts.append("## Query Errors")
            output_parts.append("\n".join(errors))

        return "\n\n".join(output_parts)

    async def indexing(
        self,
        *,
        file_paths_or_dir: list[str],
        ctx: RunContext | None = None,
        data_source: str = "all",
    ) -> str:
        rag = await self._ensure_loaded()

        message_logs = {}
        for file_path_or_dir in file_paths_or_dir:
            if os.path.isfile(file_path_or_dir):
                logger.info(
                    f"[RAGAnythingTool] Indexing func begin to process document [{file_path_or_dir}] ..."
                )
                await rag.process_document_complete(
                    file_path=file_path_or_dir,
                    output_dir=str(self.working_dir_artifacts),
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
                    output_dir=str(self.working_dir_artifacts),
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

    def close(self):
        self._previous_rags.clear()
        self._rag = None

        try:
            self._user_path_unsubscribe()
        except Exception:
            pass

        try:
            self._loop_thread.stop()
        except Exception as e:
            logger.warning("[RAGAnythingTool] Failed to stop loop thread: %s", e)
