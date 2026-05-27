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
from alphaavatar.agents import AvatarModule
from alphaavatar.agents.status import StatusEvent, StatusRendererBase, StatusType
from alphaavatar.agents.tools.deepresearch_api import DeepResearchOp


class DefaultStatusRenderer(StatusRendererBase):
    def __init__(self) -> None:
        pass

    async def render(self, event: StatusEvent) -> str | None:
        if event.message:
            return self._normalize_message(event.message)

        language = self._detect_language(event)
        return self._render_by_template(event, language=language)

    def _normalize_message(self, message: str) -> str | None:
        message = message.strip()
        if not message:
            return None

        # Keep status monologue short.
        # The final sink may trim again depending on text/voice mode.
        if len(message) > 80:
            message = message[:80].rstrip("，。,. ") + "..."

        return message

    def _detect_language(self, event: StatusEvent) -> str:
        candidates: list[str] = []

        if event.message:
            candidates.append(event.message)

        query = event.metadata.get("query")
        if isinstance(query, str):
            candidates.append(query)

        # Very simple heuristic:
        # If there are CJK characters, use Chinese. Otherwise English.
        text = "\n".join(candidates)

        if self._contains_cjk(text):
            return "zh"

        return "en"

    def _contains_cjk(self, text: str) -> bool:
        for ch in text:
            if "\u4e00" <= ch <= "\u9fff":
                return True
        return False

    def _render_by_template(self, event: StatusEvent, *, language: str) -> str | None:
        if language.startswith("zh"):
            return self._render_zh(event)

        return self._render_en(event)

    def _render_en(self, event: StatusEvent) -> str | None:
        if event.source == AvatarModule.DEEPRESEARCH:
            return self._render_deepresearch_en(event)

        if event.source == AvatarModule.MCP:
            return self._render_mcp_en(event)

        if event.source == AvatarModule.RAG:
            return self._render_rag_en(event)

        if event.source == AvatarModule.AVATAR_ENGINE:
            if event.type == StatusType.THINKING:
                return "Let me think."
            if event.type == StatusType.FINALIZING:
                return "Almost done."

        if event.type == StatusType.THINKING:
            return "Let me think."
        if event.type == StatusType.TOOL_START:
            return "I’ll check that."
        if event.type == StatusType.TOOL_PROGRESS:
            return "Still working on it."
        if event.type == StatusType.FINALIZING:
            return "Almost done."
        if event.type == StatusType.TOOL_ERROR:
            return "I’ll try another way."

        return None

    def _render_zh(self, event: StatusEvent) -> str | None:
        if event.source == AvatarModule.DEEPRESEARCH:
            return self._render_deepresearch_zh(event)

        if event.source == AvatarModule.MCP:
            return self._render_mcp_zh(event)

        if event.source == AvatarModule.RAG:
            return self._render_rag_zh(event)

        if event.source == AvatarModule.AVATAR_ENGINE:
            if event.type == StatusType.THINKING:
                return "我想一下。"
            if event.type == StatusType.FINALIZING:
                return "快好了。"

        if event.type == StatusType.THINKING:
            return "我想一下。"
        if event.type == StatusType.TOOL_START:
            return "我查一下。"
        if event.type == StatusType.TOOL_PROGRESS:
            return "还在处理。"
        if event.type == StatusType.FINALIZING:
            return "快好了。"
        if event.type == StatusType.TOOL_ERROR:
            return "我换个方式试试。"

        return None

    def _render_deepresearch_en(self, event: StatusEvent) -> str | None:
        if event.type == StatusType.TOOL_START:
            if event.stage == DeepResearchOp.SEARCH:
                return "I’ll check that."
            if event.stage == DeepResearchOp.RESEARCH:
                return "I’ll dig into it."
            if event.stage == DeepResearchOp.SCRAPE:
                return "I’m reading the sources."
            if event.stage == DeepResearchOp.DOWNLOAD:
                return "I’m saving the material."

        if event.type == StatusType.FINALIZING:
            if event.stage in {DeepResearchOp.SEARCH, DeepResearchOp.RESEARCH}:
                return "I found the main points."

        if event.type == StatusType.TOOL_ERROR:
            return "I’ll try another way."

        return "I’m checking that."

    def _render_deepresearch_zh(self, event: StatusEvent) -> str | None:
        if event.type == StatusType.TOOL_START:
            if event.stage == DeepResearchOp.SEARCH:
                return "我查一下。"
            if event.stage == DeepResearchOp.RESEARCH:
                return "我深入查一下。"
            if event.stage == DeepResearchOp.SCRAPE:
                return "我正在看资料。"
            if event.stage == DeepResearchOp.DOWNLOAD:
                return "我先保存资料。"

        if event.type == StatusType.FINALIZING:
            if event.stage in {DeepResearchOp.SEARCH, DeepResearchOp.RESEARCH}:
                return "我找到重点了。"

        if event.type == StatusType.TOOL_ERROR:
            return "我换个方式试试。"

        return "我查一下。"

    def _render_mcp_en(self, event: StatusEvent) -> str | None:
        if event.stage == "search_tools":
            return "I’m finding the right tools."
        if event.stage == "parallel_tools":
            return "I’m using a few tools."
        if event.stage == "calling_tool":
            return "I’m using a tool."
        if event.type == StatusType.TOOL_ERROR:
            return "I’ll try another way."
        return "I’m using a tool."

    def _render_mcp_zh(self, event: StatusEvent) -> str | None:
        if event.stage == "search_tools":
            return "我找一下合适的工具。"
        if event.stage == "parallel_tools":
            return "我用几个工具看一下。"
        if event.stage == "calling_tool":
            return "我用工具看一下。"
        if event.type == StatusType.TOOL_ERROR:
            return "我换个方式试试。"
        return "我用工具看一下。"

    def _render_rag_en(self, event: StatusEvent) -> str | None:
        if event.stage == "retrieving":
            return "I’ll check the documents."
        if event.stage == "reading":
            return "I found something relevant."
        if event.stage == "indexing":
            return "I’m organizing the material."
        if event.stage == "summarizing":
            return "I’m putting it together."
        return "I’m checking the documents."

    def _render_rag_zh(self, event: StatusEvent) -> str | None:
        if event.stage == "retrieving":
            return "我查一下文档。"
        if event.stage == "reading":
            return "我找到相关内容了。"
        if event.stage == "indexing":
            return "我整理一下资料。"
        if event.stage == "summarizing":
            return "我整理一下。"
        return "我查一下文档。"
