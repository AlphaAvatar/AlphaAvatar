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
"""The RAG tool's load, which its first query or indexing starts: never without its key."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from alphaavatar.plugins.rag.rag_anything import RAGAnythingTool


def _libraries(calls: list[str]) -> tuple:
    """Offline stand-ins for what the tool loads, recording each use and the key it got."""

    class LightRAG:
        def __init__(self, *, working_dir, llm_model_func, embedding_func) -> None:
            self.llm, self.embedding = llm_model_func, embedding_func

        async def initialize_storages(self) -> None:
            calls.append("storages")

        async def finalize_storages(self) -> None:
            calls.append("finalized")

    async def initialize_pipeline_status() -> None:
        calls.append("pipeline")

    async def complete(model, prompt, **options) -> str:
        calls.append(f"model:{options.get('api_key')}")
        return "answer"

    async def embed(texts, *, model, **options) -> list:
        calls.append(f"embedding:{options.get('api_key')}")
        return []

    class EmbeddingFunc:
        def __init__(self, *, embedding_dim, max_token_size, func) -> None:
            self.func = func

    class RAGAnything:
        def __init__(self, *, config, lightrag, vision_model_func) -> None:
            self.lightrag = lightrag

        async def aquery(self, query, mode) -> str:
            await self.lightrag.embedding.func([query])
            return await self.lightrag.llm(query)

        async def process_document_complete(self, file_path, output_dir) -> None:
            await self.lightrag.embedding.func([file_path])
            await self.lightrag.llm(file_path)

    return LightRAG, initialize_pipeline_status, complete, embed, EmbeddingFunc, RAGAnything, dict


def _tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> RAGAnythingTool:
    monkeypatch.setattr(RAGAnythingTool, "_dependencies", staticmethod(lambda: _libraries(calls)))
    return RAGAnythingTool(
        session_path=SimpleNamespace(artifacts_dir=tmp_path), doc_parser="docling"
    )


async def _use(tool: RAGAnythingTool, operation: str, document: Path) -> object:
    if operation == "query":
        return await tool.query(query="words")
    return await tool.indexing(file_paths_or_dir=[str(document)])


@pytest.mark.parametrize("operation", ["query", "indexing"])
@pytest.mark.parametrize("key", ["", " \t"], ids=["empty", "blank"])
async def test_without_a_key_its_first_use_names_it_and_loads_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, key: str
) -> None:
    # Its models and embeddings would read OPENAI_API_KEY themselves, blank as it is.
    calls: list[str] = []
    document = tmp_path / "document.pdf"
    document.write_bytes(b"%PDF")
    with mock.patch.dict(os.environ, {"OPENAI_API_KEY": key}):
        tool = _tool(tmp_path, monkeypatch, calls)  # Nothing loads until it is used.
        try:
            for _ in range(2):  # Asked again, it says the same, still loading nothing.
                with pytest.raises(ValueError, match=r"^OPENAI_API_KEY is required for RAG$"):
                    await _use(tool, operation, document)
        finally:
            await tool.aclose()
    assert calls == []


@pytest.mark.parametrize("operation", ["query", "indexing"])
async def test_with_its_key_it_loads_on_first_use_and_its_models_get_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    calls: list[str] = []
    document = tmp_path / "document.pdf"
    document.write_bytes(b"%PDF")
    with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-offline"}):
        tool = _tool(tmp_path, monkeypatch, calls)
        assert calls == []
        try:
            result = await _use(tool, operation, document)
        finally:
            await tool.aclose()
    assert result == "answer" or not result.is_error
    used = ["embedding:sk-offline", "model:sk-offline"]
    assert calls == ["storages", "pipeline", *used, "finalized"]
