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

import json
import logging
from typing import Any

from livekit.agents import llm
from pydantic import BaseModel

from alphaavatar.agents.avatar.provider.schemas import ModelTextPart
from alphaavatar.agents.runtime.capability import AvatarCapability, AvatarCapabilityRegistry
from alphaavatar.agents.runtime.capability.result import CapabilityResult
from alphaavatar.agents.tools.schemas import ToolError

logger = logging.getLogger(__name__)


def _legacy_result(result: Any) -> str:
    if isinstance(result, CapabilityResult):
        if any(not isinstance(part, ModelTextPart) for part in result.parts):
            raise llm.ToolError(
                "Tool execution completed, but this temporary transport cannot deliver its media. "
                "Do not repeat a potentially state-changing operation just to change its output."
            )
        text = "\n".join(part.text for part in result.parts)
        if result.is_error:
            raise llm.ToolError(text)
        return text
    if isinstance(result, BaseModel):
        result = result.model_dump(mode="json", by_alias=True)
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, allow_nan=False)


def _project(
    registry: AvatarCapabilityRegistry, capability: AvatarCapability
) -> llm.RawFunctionTool:
    async def invoke(raw_arguments: dict[str, Any]) -> str:
        try:
            result = await registry.invoke(capability.id, raw_arguments)
        except ToolError as exc:
            raise llm.ToolError(str(exc)) from None
        except Exception:
            logger.exception("Capability failed name=%s", capability.id)
            raise llm.ToolError(
                "Tool execution failed. A state-changing operation may have an unknown outcome; "
                "do not retry it blindly."
            ) from None
        return _legacy_result(result)

    return llm.function_tool(
        invoke,
        raw_schema={
            "name": capability.tool_name,
            "description": capability.description,
            "parameters": capability.parameters,
            "strict": False,
        },
    )


def build_function_tools(registry: AvatarCapabilityRegistry) -> list[llm.Tool]:
    """Temporary SDK projection only. Names, schemas, validation and invocation remain native."""
    return [_project(registry, value) for value in registry.capabilities if value.callable]
