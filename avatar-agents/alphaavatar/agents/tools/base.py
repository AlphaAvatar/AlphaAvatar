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
import inspect
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from livekit.agents import RunContext, function_tool, llm
from livekit.agents.llm import ToolError

from alphaavatar.agents.status import (
    StatusEmitter,
    StatusEvent,
    StatusPriority,
    StatusType,
)


class ToolBase(ABC):
    """Base class for all tools used by agents in the AlphaAvatar framework."""

    def __init__(
        self,
        *,
        name: str,
        description: str,
        status_emitter: StatusEmitter | None = None,
    ):
        self._name = name
        self._description = description
        self._status_emitter = status_emitter

        tool_func = self._build_tool_wrapper()
        self._tool = function_tool(name=self._name, description=self._description)(tool_func)

    @property
    def tool(self) -> llm.FunctionTool | llm.RawFunctionTool:
        return self._tool

    @property
    def status_emitter(self) -> StatusEmitter | None:
        return self._status_emitter

    def set_status_emitter(self, status_emitter: StatusEmitter | None) -> None:
        self._status_emitter = status_emitter

    async def emit_status(self, event: StatusEvent) -> None:
        """Awaitable status emit. Use this when ordering matters."""
        if self._status_emitter is None:
            return

        await self._status_emitter.emit(event)

    def emit_status_nowait(self, event: StatusEvent):
        """
        Fire-and-forget status emit.

        This is preferred before long-running tool calls, so status delivery
        does not block the actual tool execution.
        """
        if self._status_emitter is None:
            return None

        return self._status_emitter.emit_nowait(event)

    def emit_status_delayed(
        self,
        event: StatusEvent,
        *,
        delay_sec: float | None = None,
    ):
        if self._status_emitter is None:
            return None

        return self._status_emitter.emit_delayed(event, delay_sec=delay_sec)

    def _build_tool_wrapper(self):
        """
        Build an async function with the same signature as self.invoke,
        so LiveKit can attach metadata and build strict OpenAI schema.

        Also catches runtime errors, emits TOOL_ERROR status, and converts
        unexpected exceptions into ToolError so the LLM can recover.
        """
        invoke = self.invoke
        sig = inspect.signature(invoke)

        params = list(sig.parameters.values())

        for p in params:
            if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                raise TypeError(
                    f"{self.__class__.__name__}.invoke must not use *args/**kwargs in strict tool schema mode."
                )

        ns = {
            "__invoke": invoke,
            "__handle_tool_error": self._handle_tool_error,
            "ToolError": ToolError,
        }

        param_chunks = []
        call_chunks = []

        saw_kwonly = False
        default_i = 0

        for p in params:
            if p.kind == inspect.Parameter.KEYWORD_ONLY and not saw_kwonly:
                param_chunks.append("*")
                saw_kwonly = True

            if p.default is inspect._empty:
                param_chunks.append(p.name)
            else:
                dn = f"__d{default_i}"
                default_i += 1
                ns[dn] = p.default
                param_chunks.append(f"{p.name}={dn}")

            call_chunks.append(p.name)

        params_src = ", ".join(param_chunks)
        call_src = ", ".join(call_chunks)

        src = f"""
async def __tool({params_src}):
    try:
        return await __invoke({call_src})
    except ToolError as e:
        await __handle_tool_error(e)
        raise
    except Exception as e:
        await __handle_tool_error(e)
        raise ToolError("The tool call failed. Please recover or try another way.")
"""
        exec(src, ns, ns)
        tool_func = ns["__tool"]

        tool_func.__annotations__ = dict(getattr(invoke, "__annotations__", {}))

        return tool_func

    async def _handle_tool_error(self, error: Exception) -> None:
        self.emit_status_nowait(
            StatusEvent(
                type=StatusType.TOOL_ERROR,
                source=self._status_source(),
                stage=self._status_stage(),
                priority=StatusPriority.HIGH,
                metadata={
                    "tool_name": self._name,
                    "tool_class": self.__class__.__name__,
                    "error_type": error.__class__.__name__,
                    "error": str(error),
                },
            )
        )

    def _status_source(self) -> str | StrEnum:
        return self._name

    def _status_stage(self) -> str | StrEnum:
        return "tool_error"

    @abstractmethod
    async def invoke(self, ctx: RunContext, *args, **kwargs) -> Any: ...
