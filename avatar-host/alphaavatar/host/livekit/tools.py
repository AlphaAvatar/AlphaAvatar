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

import asyncio
import json
import logging
from typing import Any

from livekit.agents import RunContext, llm
from pydantic import BaseModel

from alphaavatar.agents.avatar.provider.schemas import ModelTextPart
from alphaavatar.agents.runtime.capability import AvatarCapability, AvatarCapabilityRegistry
from alphaavatar.agents.runtime.capability.result import CapabilityResult
from alphaavatar.agents.tools.schemas import ToolError
from alphaavatar.core.output.enums import ExecutionSignalKind

from .execution import LiveKitExecutionBridge

logger = logging.getLogger(__name__)


def _legacy_result(result: Any) -> str:
    if isinstance(result, CapabilityResult):
        if any(not isinstance(part, ModelTextPart) for part in result.parts):
            raise llm.ToolError(
                "Tool execution completed, but this temporary transport cannot deliver its media. "
                "Do not repeat a state-changing operation just to change its output."
            )
        text = "\n".join(part.text for part in result.parts)
        if result.is_error:
            raise llm.ToolError(text)
        return text
    if isinstance(result, BaseModel):
        result = result.model_dump(mode="json", by_alias=True)
    return (
        result
        if isinstance(result, str)
        else json.dumps(result, ensure_ascii=False, allow_nan=False)
    )


def _project(
    registry: AvatarCapabilityRegistry, capability: AvatarCapability, bridge: LiveKitExecutionBridge
) -> llm.RawFunctionTool:
    async def invoke(raw_arguments: dict[str, Any], ctx: RunContext) -> str:
        step = bridge.tool_step(ctx)
        executed, outcome = False, "failed"
        try:
            capability.parse(raw_arguments)
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                raise asyncio.CancelledError
            if step is not None:
                bridge.signal(
                    step,
                    ExecutionSignalKind.TOOL_STARTED,
                    "tools",
                    call_id=ctx.function_call.call_id,
                    tool_name=capability.tool_name,
                    executed=True,
                )
            executed = True
            result = await registry.invoke(capability.id, raw_arguments)
            failed = isinstance(result, CapabilityResult) and result.is_error
            outcome = "failed" if failed else "succeeded"
            return _legacy_result(result)
        except asyncio.CancelledError:
            outcome = "unknown" if executed else "cancelled"
            raise
        except ToolError as exc:
            outcome = "unknown" if executed else "failed"
            raise llm.ToolError(str(exc)) from None
        except llm.ToolError:
            raise
        except Exception:
            outcome = "unknown" if executed else "failed"
            logger.exception("Capability failed name=%s", capability.id)
            raise llm.ToolError(
                "Tool execution failed. A state-changing operation may have an unknown outcome; "
                "do not retry it blindly."
            ) from None
        finally:
            if step is not None:
                bridge.signal(
                    step,
                    ExecutionSignalKind.TOOL_FINISHED,
                    "tools",
                    call_id=ctx.function_call.call_id,
                    tool_name=capability.tool_name,
                    outcome=outcome,
                    executed=executed,
                )

    return llm.function_tool(
        invoke,
        raw_schema={
            "name": capability.tool_name,
            "description": capability.description,
            "parameters": capability.parameters,
            "strict": False,
        },
    )


def build_function_tools(
    registry: AvatarCapabilityRegistry, *, bridge: LiveKitExecutionBridge
) -> list[llm.Tool]:
    return [
        _project(registry, capability, bridge)
        for capability in registry.capabilities
        if capability.callable
    ]
