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
import os
import pathlib

from livekit.agents import NOT_GIVEN, NotGivenOr, RunContext
from tavily import TavilyClient

from alphaavatar.agents.tools import DeepResearchBase
from alphaavatar.agents.utils import url_to_filename_id
from alphaavatar.agents.utils.files import save_single_url_content_to_pdf

from .log import logger
from .schema.tavily_obj import TavilyExtractObj

SEARCH_INSTANCE = "tavily"


class TavilyDeepResearchTool(DeepResearchBase):
    def __init__(
        self,
        *args,
        working_dir: pathlib.Path,
        tavily_api_key: NotGivenOr[str] = NOT_GIVEN,
        **kwargs,
    ) -> None:
        super().__init__()

        self._working_dir = working_dir / SEARCH_INSTANCE
        self._tavily_api_key = tavily_api_key or (os.getenv("TAVILY_API_KEY") or NOT_GIVEN)

        if not self._tavily_api_key:
            raise ValueError("TAVILY_API_KEY must be set by arguments or environment variables")

        self._tavily_client = TavilyClient(api_key=self._tavily_api_key)

    def _get_page_content(self, urls: list[str]) -> dict[str]:
        res = self._tavily_client.extract(urls=urls, include_images=True, format="markdown")
        return TavilyExtractObj.from_dict(res)

    async def search(
        self,
        *,
        query: str,
        ctx: RunContext | None = None,
    ) -> dict:
        logger.info(f"[TavilyDeepResearchTool] search func by query: {query}")
        res: dict[str] = self._tavily_client.search(
            query=query, search_depth="basic", max_results=5
        )
        return res

    async def research(
        self,
        *,
        query: str,
        ctx: RunContext | None = None,
    ) -> dict:
        logger.info(f"[TavilyDeepResearchTool] research func by query: {query}")
        res = self._tavily_client.search(query=query, search_depth="advanced", max_results=5)
        return res

    async def scrape(self, *, urls: list[str], ctx: RunContext | None = None) -> str:
        logger.info(f"[TavilyDeepResearchTool] scrape func by urls: {urls}")
        extract_obj: TavilyExtractObj = self._get_page_content(urls=urls)
        return extract_obj.to_markdown()

    async def download(self, *, urls: list[str], ctx: RunContext | None = None) -> str:
        logger.info(f"[TavilyDeepResearchTool] download func by urls: {urls}")

        res: TavilyExtractObj = self._get_page_content(urls=urls)

        out_root = self._working_dir.resolve()
        saved_lines: list[str] = []
        for idx, item in enumerate(res.results, start=1):
            safe_name = url_to_filename_id(item.url)
            page_dir = self._working_dir / safe_name
            page_dir.mkdir(parents=True, exist_ok=True)

            out_pdf = (page_dir / f"{safe_name}_page.pdf").resolve()

            save_single_url_content_to_pdf(
                url=item.url,
                title=item.title,
                markdown_content=item.raw_content,
                output_pdf_path=str(out_pdf),
                work_dir=page_dir,
                extra_image_urls=item.images,
            )

            title = (item.title or "").strip() or "Untitled"
            saved_lines.append(
                f"{idx}. Title: {title}\n   URL: {item.url}\n   Saved PDF: {out_pdf}\n"
            )

        failed_lines: list[str] = []
        if res.failed_results:
            for idx, fr in enumerate(res.failed_results, start=1):
                failed_lines.append(f"{idx}. {fr}")

        summary = [
            "✅ All URLs have been downloaded and saved successfully.",
            f"Root output directory: {out_root}",
            "",
            "Saved files:",
            *saved_lines,
        ]

        if failed_lines:
            summary += [
                "",
                "⚠️ Failed results:",
                *failed_lines,
            ]

        return "\n".join(summary)
