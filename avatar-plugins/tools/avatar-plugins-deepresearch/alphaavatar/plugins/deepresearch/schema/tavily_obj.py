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

from dataclasses import dataclass
from typing import Any


@dataclass
class TavilyExtractResult:
    url: str
    title: str
    raw_content: str
    images: list[str]

    @staticmethod
    def from_dict(d: dict[str, Any]) -> TavilyExtractResult:
        return TavilyExtractResult(
            url=d.get("url", ""),
            title=d.get("title", ""),
            raw_content=d.get("raw_content", "") or "",
            images=list(d.get("images", []) or []),
        )


@dataclass
class TavilyExtractObj:
    results: list[TavilyExtractResult]
    failed_results: list[dict[str, Any]]
    response_time: float | None = None
    request_id: str | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> TavilyExtractObj:
        results = [TavilyExtractResult.from_dict(x) for x in (d.get("results") or [])]
        return TavilyExtractObj(
            results=results,
            failed_results=list(d.get("failed_results") or []),
            response_time=d.get("response_time"),
            request_id=d.get("request_id"),
        )

    def to_markdown(self) -> str:
        """
        Convert this TavilyExtractObj into a single Markdown document
        containing all extracted pages and metadata.
        """
        lines: list[str] = []

        # ===== Header / Metadata =====
        lines.append("# Tavily Extract Results")
        lines.append("")

        if self.request_id:
            lines.append(f"- **request_id**: `{self.request_id}`")
        if self.response_time is not None:
            lines.append(f"- **response_time**: `{self.response_time}`")
        lines.append(f"- **total_results**: `{len(self.results)}`")
        lines.append(f"- **failed_results**: `{len(self.failed_results)}`")
        lines.append("")
        lines.append("---")
        lines.append("")

        # ===== Each Result =====
        for idx, r in enumerate(self.results, start=1):
            title = (r.title or "").strip() or "Untitled"

            lines.append(f"# {idx}. {title}")
            lines.append("")
            lines.append(f"- **URL**: {r.url}")

            if r.images:
                lines.append(f"- **Images ({len(r.images)})**:")
                for img in r.images:
                    # Markdown list + clickable url
                    lines.append(f"  - {img}")
            else:
                lines.append("- **Images**: (none)")

            lines.append("")
            lines.append("## Raw Content (Markdown)")
            lines.append("")
            lines.append(r.raw_content.strip() if r.raw_content else "(empty)")
            lines.append("")
            lines.append("---")
            lines.append("")

        # ===== Failed Results =====
        if self.failed_results:
            import json

            lines.append("# Failed Results")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(self.failed_results, ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")

        return "\n".join(lines)


@dataclass
class TavilySearchResult:
    url: str
    title: str | None = None
    content: str | None = None
    score: float | None = None
    raw_content: str | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> TavilySearchResult:
        return TavilySearchResult(
            url=str(d.get("url") or ""),
            title=d.get("title"),
            content=d.get("content"),
            score=d.get("score"),
            raw_content=d.get("raw_content"),
        )


@dataclass
class TavilySearchObj:
    query: str | None
    follow_up_questions: Any = None
    answer: str | None = None
    images: list[str] | None = None

    results: list[TavilySearchResult] | None = None
    failed_results: list[dict[str, Any]] | None = None

    response_time: float | None = None
    request_id: str | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> TavilySearchObj:
        results = [TavilySearchResult.from_dict(x) for x in (d.get("results") or [])]
        return TavilySearchObj(
            query=d.get("query"),
            follow_up_questions=d.get("follow_up_questions"),
            answer=d.get("answer"),
            images=list(d.get("images") or []),
            results=results,
            failed_results=list(d.get("failed_results") or []),
            response_time=d.get("response_time"),
            request_id=d.get("request_id"),
        )

    def to_markdown(
        self,
        *,
        title: str = "Tavily Search Results",
        max_results: int | None = None,
        max_content_chars: int = 600,
        include_answer: bool = False,
        include_images: bool = False,
        include_follow_ups: bool = False,
    ) -> str:
        """
        Convert TavilySearchObj into a single Markdown evidence document for LLM.
        - Default: focus on results snippets + sources (URLs) + scores.
        - Truncates content to avoid token explosion.
        """

        def _truncate(text: str, limit: int) -> str:
            text = (text or "").strip()
            if not text:
                return ""
            if len(text) <= limit:
                return text
            return text[:limit].rstrip() + "…"

        lines: list[str] = []

        # ===== Header / Metadata =====
        lines.append(f"# {title}")
        lines.append("")

        if self.query:
            lines.append(f"**Query:** {self.query}")
            lines.append("")

        if self.request_id:
            lines.append(f"- **request_id**: `{self.request_id}`")
        if self.response_time is not None:
            lines.append(f"- **response_time**: `{self.response_time}`")

        results = self.results or []
        failed = self.failed_results or []

        lines.append(f"- **total_results**: `{len(results)}`")
        if failed:
            lines.append(f"- **failed_results**: `{len(failed)}`")

        if include_answer and self.answer:
            lines.append(f"- **answer**: {self.answer}")
        if include_follow_ups and self.follow_up_questions:
            lines.append(f"- **follow_up_questions**: `{self.follow_up_questions}`")
        if include_images and (self.images or []):
            lines.append(f"- **images**: `{len(self.images or [])}`")

        lines.append("")
        lines.append("---")
        lines.append("")

        # ===== Each Result =====
        if max_results is not None:
            results = results[:max_results]

        for idx, r in enumerate(results, start=1):
            title_txt = (r.title or "").strip() or "Untitled"
            url = (r.url or "").strip()

            lines.append(f"## Result {idx}: {title_txt}")
            if url:
                lines.append(f"- **URL**: {url}")
            if r.score is not None:
                lines.append(f"- **Relevance Score**: `{r.score:.4f}`")

            snippet = _truncate(r.content or "", max_content_chars)
            lines.append("")
            if snippet:
                # blockquote -> evidence
                lines.append(f"> {snippet}")
            else:
                lines.append("> _(No snippet available)_")

            if r.raw_content:
                lines.append("")
                lines.append("<details>")
                lines.append("<summary>Raw Content</summary>")
                lines.append("")
                lines.append(r.raw_content.strip())
                lines.append("")
                lines.append("</details>")

            lines.append("")
            lines.append("---")
            lines.append("")

        # ===== Failed Results =====
        if failed:
            import json

            lines.append("# Failed Results")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(failed, ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")

        return "\n".join(lines).strip()
