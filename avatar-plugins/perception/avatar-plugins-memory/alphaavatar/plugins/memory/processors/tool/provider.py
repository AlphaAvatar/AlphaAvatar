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
from typing import Any

from alphaavatar.agents.providers import ProviderGateway

from ...log import logger
from ...schemas.patch import MemoryDelta
from .config import ToolProviderConfig
from .prompt import TOOL_DELTA_PROMPT


class ToolProvider:
    def __init__(
        self,
        config: ToolProviderConfig,
    ) -> None:
        self._task = config.task
        self._gateway = ProviderGateway(config.gateway)
        self._gateway.validate_tasks([self._task])

    async def extract(
        self,
        *,
        context_content: str,
        metadata: dict[str, Any],
        timeout: float = 30.0,
    ) -> MemoryDelta:
        try:
            result = await asyncio.wait_for(
                self._gateway.ainvoke_structured(
                    task_name=self._task,
                    prompt=TOOL_DELTA_PROMPT,
                    payload={
                        "session_content": context_content,
                    },
                    output_schema=MemoryDelta,
                    metadata=metadata,
                ),
                timeout=timeout,
            )

            return (
                result.output
                if isinstance(result.output, MemoryDelta)
                else MemoryDelta.model_validate(result.output)
            )

        except TimeoutError:
            logger.warning(
                "[Memory] tool provider timeout task=%s timeout=%s",
                self._task,
                timeout,
            )
            return MemoryDelta()

        except asyncio.CancelledError:
            raise

        except Exception:
            logger.exception(
                "[Memory] tool provider failed task=%s",
                self._task,
            )
            return MemoryDelta()
