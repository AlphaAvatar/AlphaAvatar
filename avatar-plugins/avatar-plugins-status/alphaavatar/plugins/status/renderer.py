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

_AVATAR_ENGINE_SOURCE = "avatar_engine"
_LLM_SOURCE = "llm"


class DefaultStatusRenderer(StatusRendererBase):
    def __init__(
        self,
        *,
        default_language: str = "en",
        enable_llm: bool = False,
    ) -> None:
        self.default_language = default_language
        self.enable_llm = enable_llm

    async def render(self, event: StatusEvent) -> str | None:
        if event.render_mode == "none":
            return None

        if event.message:
            return event.message

        language = event.language or self.default_language

        if event.render_mode == "llm":
            return await self._render_by_llm(event, language=language)

        if event.render_mode == "template":
            return self._render_by_template(event, language=language)

        if self._should_use_llm(event):
            llm_text = await self._render_by_llm(event, language=language)
            if llm_text:
                return llm_text

        return self._render_by_template(event, language=language)

    def _should_use_llm(self, event: StatusEvent) -> bool:
        if not self.enable_llm:
            return False

        if event.source in {AvatarModule.MEMORY, AvatarModule.PERSONA}:
            return False

        if event.source == _AVATAR_ENGINE_SOURCE and event.type in {
            StatusType.THINKING,
            StatusType.FINALIZING,
        }:
            return True

        if event.source == AvatarModule.DEEPRESEARCH and event.type == StatusType.FINALIZING:
            return True

        return False

    async def _render_by_llm(self, event: StatusEvent, *, language: str) -> str | None:
        # Future extension:
        # call a small model here.
        return self._render_by_template(event, language=language)

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

        if event.source == _AVATAR_ENGINE_SOURCE:
            if event.type == StatusType.THINKING:
                return "Let me think for a moment."
            if event.type == StatusType.FINALIZING:
                return "I have the result and I’m preparing the response."

        if event.source == _LLM_SOURCE:
            if event.type == StatusType.THINKING:
                return "Let me think for a moment."
            if event.type == StatusType.FINALIZING:
                return "I’m preparing the final response."

        if event.type == StatusType.THINKING:
            return "Let me think for a moment."
        if event.type == StatusType.TOOL_START:
            return "I’m calling a tool."
        if event.type == StatusType.TOOL_PROGRESS:
            return "I’m still working on it."
        if event.type == StatusType.FINALIZING:
            return "I’m preparing the final response."

        return None

    def _render_zh(self, event: StatusEvent) -> str | None:
        if event.source == AvatarModule.DEEPRESEARCH:
            return self._render_deepresearch_zh(event)

        if event.source == AvatarModule.MCP:
            return self._render_mcp_zh(event)

        if event.source == AvatarModule.RAG:
            return self._render_rag_zh(event)

        if event.source == _AVATAR_ENGINE_SOURCE:
            if event.type == StatusType.THINKING:
                return "我想一下。"
            if event.type == StatusType.FINALIZING:
                return "我已经拿到结果，正在整理回复。"

        if event.source == _LLM_SOURCE:
            if event.type == StatusType.THINKING:
                return "我想一下。"
            if event.type == StatusType.FINALIZING:
                return "我正在整理最终回复。"

        if event.type == StatusType.THINKING:
            return "我想一下。"
        if event.type == StatusType.TOOL_START:
            return "我正在调用工具处理。"
        if event.type == StatusType.TOOL_PROGRESS:
            return "我还在处理中。"
        if event.type == StatusType.FINALIZING:
            return "我正在整理回复。"

        return None

    def _render_deepresearch_en(self, event: StatusEvent) -> str | None:
        if event.type == StatusType.TOOL_START:
            if event.stage == DeepResearchOp.SEARCH:
                return "I’m searching for relevant information."
            if event.stage == DeepResearchOp.RESEARCH:
                return "I’m starting a deeper research pass."
            if event.stage == DeepResearchOp.SCRAPE:
                return "I’m reading through the source content."
            if event.stage == DeepResearchOp.DOWNLOAD:
                return "I’m saving the relevant materials for analysis."

        if event.type == StatusType.FINALIZING:
            if event.stage in {DeepResearchOp.SEARCH, DeepResearchOp.RESEARCH}:
                return "I’ve gathered the materials and I’m summarizing the key points."

        if event.type == StatusType.TOOL_ERROR:
            return "The research tool hit an issue, but I’m trying to continue."

        return "I’m working on this research task."

    def _render_deepresearch_zh(self, event: StatusEvent) -> str | None:
        if event.type == StatusType.TOOL_START:
            if event.stage == DeepResearchOp.SEARCH:
                return "我正在帮你搜索相关资料。"
            if event.stage == DeepResearchOp.RESEARCH:
                return "我正在做更深入的资料调研。"
            if event.stage == DeepResearchOp.SCRAPE:
                return "我正在读取这些网页内容。"
            if event.stage == DeepResearchOp.DOWNLOAD:
                return "我正在保存相关资料，方便后续分析。"

        if event.type == StatusType.FINALIZING:
            if event.stage in {DeepResearchOp.SEARCH, DeepResearchOp.RESEARCH}:
                return "资料已经收集得差不多了，我正在总结重点。"

        if event.type == StatusType.TOOL_ERROR:
            return "调研工具遇到了一点问题，我正在尝试继续处理。"

        return "我正在处理这个研究任务。"

    def _render_mcp_en(self, event: StatusEvent) -> str | None:
        # TODO:
        # Replace string stages with MCP op enum after MCP status events are typed.
        if event.stage == "search_tools":
            return "I’m looking for the right external tools."
        if event.stage == "parallel_tools":
            return "I’m calling a few external tools in parallel."
        if event.stage == "calling_tool":
            return "I’m calling an external tool."
        if event.type == StatusType.TOOL_ERROR:
            return "The tool call hit an issue, but I’m trying to continue."
        return "I’m using external tools to process this."

    def _render_mcp_zh(self, event: StatusEvent) -> str | None:
        # TODO:
        # Replace string stages with MCP op enum after MCP status events are typed.
        if event.stage == "search_tools":
            return "我正在查找可用的外部工具。"
        if event.stage == "parallel_tools":
            return "我正在并行调用几个外部工具。"
        if event.stage == "calling_tool":
            return "我正在调用外部工具处理。"
        if event.type == StatusType.TOOL_ERROR:
            return "工具调用遇到了一点问题，我正在尝试继续处理。"
        return "我正在通过外部工具处理。"

    def _render_rag_en(self, event: StatusEvent) -> str | None:
        # TODO:
        # Replace string stages with RAG op enum after RAG status events are typed.
        if event.stage == "retrieving":
            return "I’m retrieving relevant documents."
        if event.stage == "reading":
            return "I found some relevant content and I’m reading it."
        if event.stage == "indexing":
            return "I’m organizing and indexing the materials."
        if event.stage == "summarizing":
            return "I’m preparing an answer based on the documents."
        return "I’m processing the document information."

    def _render_rag_zh(self, event: StatusEvent) -> str | None:
        # TODO:
        # Replace string stages with RAG op enum after RAG status events are typed.
        if event.stage == "retrieving":
            return "我正在检索相关文档。"
        if event.stage == "reading":
            return "我找到了一些相关内容，正在读取。"
        if event.stage == "indexing":
            return "我正在整理并索引这些资料。"
        if event.stage == "summarizing":
            return "我正在根据文档整理答案。"
        return "我正在处理文档信息。"
