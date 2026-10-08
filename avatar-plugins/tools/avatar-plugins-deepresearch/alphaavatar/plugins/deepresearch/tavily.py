# Copyright 2025 AlphaAvatar project
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
import os
from typing import TYPE_CHECKING, Any

import httpx

from alphaavatar.agents.avatar.provider.schemas import ModelTextPart
from alphaavatar.agents.runtime.capability.result import CapabilityResult
from alphaavatar.agents.tools.schemas import ToolError
from alphaavatar.agents.utils import url_to_filename_id
from alphaavatar.core.cleanup import wait_for_cleanup

from .schemas import TavilyExtractObj, TavilySearchObj

if TYPE_CHECKING:
    from alphaavatar.agents.utils.files.work_dirs import SessionPath


class TavilyDeepResearchTool:
    """Async HTTP requests; unavoidable document conversion stays in owned worker tasks."""

    def __init__(
        self,
        *,
        session_path: SessionPath,
        tavily_api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        key = tavily_api_key or os.getenv("TAVILY_API_KEY")
        if not key:
            raise ValueError("TAVILY_API_KEY is required")
        if not 0 < timeout < float("inf"):
            raise ValueError("Tavily timeout must be finite and positive")

        self.session_path = session_path
        self._client = httpx.AsyncClient(
            base_url="https://api.tavily.com",
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
            follow_redirects=False,
        )
        self._workers: set[asyncio.Task[CapabilityResult]] = set()
        self._close_task: asyncio.Task[None] | None = None

    @staticmethod
    def _observe(task: asyncio.Task[CapabilityResult]) -> None:
        if not task.cancelled():
            task.exception()

    def _save(self, result: TavilyExtractObj) -> CapabilityResult:
        from alphaavatar.agents.utils.files import save_single_url_content_to_pdf

        root = (self.session_path.artifacts_dir / "tavily").resolve()
        saved, failures = [], [str(value) for value in (result.failed_results or [])]
        for item in result.results:
            name = url_to_filename_id(item.url)
            directory = root / name
            target = directory / f"{name}_page.pdf"
            try:
                directory.mkdir(parents=True, exist_ok=True)
                save_single_url_content_to_pdf(
                    url=item.url,
                    title=item.title,
                    markdown_content=item.raw_content,
                    output_pdf_path=str(target),
                    work_dir=directory,
                    extra_image_urls=item.images,
                )
            except Exception:
                failures.append(f"Document conversion failed: {item.url}")
                continue
            saved.append(f"Title: {item.title or 'Untitled'}\nURL: {item.url}\nSaved PDF: {target}")

        summary = [f"Saved {len(saved)} documents; {len(failures)} failures.", *saved]
        if failures:
            summary.extend(("Failed results:", *failures))
        return CapabilityResult(
            parts=(ModelTextPart("\n\n".join(summary)),), is_error=bool(failures) or not saved
        )

    async def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self._close_task is not None:
            raise RuntimeError("Tavily client is closed")
        response = await self._client.post(endpoint, json=payload)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            message = f"Public-web service returned HTTP {exc.response.status_code}"
            raise ToolError(message) from None
        result = response.json()
        if not isinstance(result, dict):
            raise ToolError("Public-web service returned an invalid response")
        return result

    async def _search(self, query: str, *, depth: str) -> str:
        result = await self._post(
            "/search", {"query": query, "search_depth": depth, "max_results": 5}
        )
        return TavilySearchObj.from_dict(result).to_markdown()

    async def _extract(self, urls: list[str]) -> TavilyExtractObj:
        result = await self._post(
            "/extract", {"urls": urls, "include_images": True, "format": "markdown"}
        )
        return TavilyExtractObj.from_dict(result)

    async def search(self, *, query: str) -> str:
        return await self._search(query, depth="basic")

    async def research(self, *, query: str) -> str:
        # Preserve the existing deeper-search operation, not an untracked background research job.
        return await self._search(query, depth="advanced")

    async def scrape(self, *, urls: list[str]) -> CapabilityResult:
        result = await self._extract(urls)
        return CapabilityResult(
            parts=(ModelTextPart(result.to_markdown()),),
            is_error=bool(result.failed_results) or not result.results,
        )

    async def download(self, *, urls: list[str]) -> CapabilityResult:
        result = await self._extract(urls)
        task = asyncio.create_task(
            asyncio.to_thread(self._save, result), name="tavily_document_save"
        )
        self._workers.add(task)
        task.add_done_callback(self._workers.discard)
        task.add_done_callback(self._observe)
        # A cancelled caller must not abandon ownership of a still-running document conversion.
        return await asyncio.shield(task)

    async def _close(self) -> None:
        try:
            await asyncio.gather(*tuple(self._workers), return_exceptions=True)
        finally:
            await self._client.aclose()

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="tavily_close")
        await wait_for_cleanup(self._close_task)
