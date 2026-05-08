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

from livekit.agents import llm

RUNTIME_CONTEXT_TOOL_NAME = "alphaavatar_runtime_context"


async def alphaavatar_runtime_context() -> str:
    """
    Internal AlphaAvatar runtime context carrier.

    This tool should not be called by the model directly.
    AlphaAvatar injects its function call/output pair synthetically before LLM generation.
    """
    return "AlphaAvatar runtime context is injected internally. Do not call this tool directly."


def get_runtime_context_tool() -> llm.FunctionTool:
    return llm.function_tool(
        alphaavatar_runtime_context,
        name=RUNTIME_CONTEXT_TOOL_NAME,
        description=(
            "Internal AlphaAvatar runtime context carrier. "
            "Do not call this tool directly. "
            "Runtime context is injected by the AlphaAvatar engine."
        ),
    )
