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

from alphaavatar.agents.router import (
    SemanticAddressingModelBase,
    SemanticAddressingRequest,
    SemanticAddressingResult,
)
from alphaavatar.agents.runtime.inference import InferenceExecutor

from .runner import SemanticAddressingQwen3Runner


class Qwen3SemanticAddressingModel(SemanticAddressingModelBase):
    def __init__(self, *, inference_executor: InferenceExecutor) -> None:
        self._executor = inference_executor
        self._inflight: set[asyncio.Task[bytes | None]] = set()

    @property
    def name(self) -> str:
        return "qwen3_0_6b_q8_0"

    def _track(self, task: asyncio.Task[bytes | None]) -> None:
        self._inflight.add(task)

        def done(completed: asyncio.Task[bytes | None]) -> None:
            self._inflight.discard(completed)
            if not completed.cancelled():
                try:
                    completed.exception()
                except Exception:
                    pass

        task.add_done_callback(done)

    async def assess(self, request: SemanticAddressingRequest) -> SemanticAddressingResult:
        task = asyncio.create_task(
            self._executor.do_inference(
                SemanticAddressingQwen3Runner.INFERENCE_METHOD,
                json.dumps(request.to_dict(), separators=(",", ":")).encode(),
            ),
            name="semantic_addressing_inference",
        )
        self._track(task)
        payload = await asyncio.shield(task)

        if payload is None:
            raise RuntimeError("Semantic Addressing runner returned no result")

        return SemanticAddressingResult.from_dict(json.loads(payload))
