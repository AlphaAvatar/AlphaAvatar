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
from typing import Any, TypeVar

from pydantic import BaseModel

from alphaavatar.agents.providers import ProviderGateway

from ...log import logger
from ...schemas.patch import MemoryDelta
from .config import ConversationProviderConfig
from .consolidation import (
    CONSOLIDATION_PROMPT,
    SESSION_SUMMARY_PROMPT,
    ConsolidationPlan,
)
from .prompt import build_conversation_delta_prompt

TStructuredOutput = TypeVar(
    "TStructuredOutput",
    bound=BaseModel,
)


class ConversationProvider:
    def __init__(
        self,
        config: ConversationProviderConfig,
    ) -> None:
        self._task = config.task
        self._gateway = ProviderGateway(config.gateway)
        self._gateway.validate_tasks([self._task])

    async def _invoke(
        self,
        *,
        prompt: Any,
        payload: dict[str, Any],
        output_schema: type[TStructuredOutput],
        fallback: TStructuredOutput,
        metadata: dict[str, Any],
        timeout: float,
    ) -> TStructuredOutput:
        try:
            result = await asyncio.wait_for(
                self._gateway.ainvoke_structured(
                    task_name=self._task,
                    prompt=prompt,
                    payload=payload,
                    output_schema=output_schema,
                    metadata=metadata,
                ),
                timeout=timeout,
            )

            return (
                result.output
                if isinstance(result.output, output_schema)
                else output_schema.model_validate(result.output)
            )

        except TimeoutError:
            logger.warning(
                "[Memory] conversation provider timeout task=%s timeout=%s",
                self._task,
                timeout,
            )
            return fallback

        except asyncio.CancelledError:
            raise

        except Exception:
            logger.exception(
                "[Memory] conversation provider failed task=%s",
                self._task,
            )
            return fallback

    async def extract(
        self,
        *,
        context_content: str,
        session_gate: bool,
        metadata: dict[str, Any],
        timeout: float = 30.0,
    ) -> MemoryDelta:
        return await self._invoke(
            prompt=build_conversation_delta_prompt(
                session_gate=session_gate,
            ),
            payload={"session_content": context_content},
            output_schema=MemoryDelta,
            fallback=MemoryDelta(),
            metadata=metadata,
            timeout=timeout,
        )

    async def plan_consolidation(
        self,
        *,
        payload: dict[str, Any],
        session_summary: bool,
        metadata: dict[str, Any],
        timeout: float,
    ) -> ConsolidationPlan:
        return await self._invoke(
            prompt=(SESSION_SUMMARY_PROMPT if session_summary else CONSOLIDATION_PROMPT),
            payload=payload,
            output_schema=ConsolidationPlan,
            fallback=ConsolidationPlan(),
            metadata=metadata,
            timeout=timeout,
        )
