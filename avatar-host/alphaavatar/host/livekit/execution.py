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
import logging
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING
from uuid import uuid4

from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.output.enums import ExecutionSignalKind
from alphaavatar.core.output.schemas import OutputExecutionSignal, OutputScope

if TYPE_CHECKING:
    from livekit.agents import RunContext

    from alphaavatar.agents.runtime import AvatarRuntime
    from alphaavatar.core.turn import TurnSnapshot

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SDKStep:
    scope: OutputScope
    request_id: str
    model_step: int
    commentary_output_ids: tuple[str, ...] = ()


@dataclass(slots=True)
class _Speech:
    step: SDKStep
    watcher: asyncio.Task | None = None
    failure: str | None = None


class LiveKitExecutionBridge:
    """Temporary SDK facts only; no presentation policy, narration, or model/tool executor."""

    def __init__(self, runtime: AvatarRuntime) -> None:
        self._runtime = runtime
        self._speeches: dict[str, _Speech] = {}
        self._close_task: asyncio.Task | None = None

    def signal(self, step: SDKStep, kind: ExecutionSignalKind, state: str, **fields) -> None:
        try:
            self._runtime.output.publish_execution(
                OutputExecutionSignal(
                    scope=step.scope,
                    kind=kind,
                    state=state,
                    request_id=step.request_id,
                    model_step=step.model_step,
                    commentary_output_ids=step.commentary_output_ids,
                    **fields,
                )
            )
        except Exception:
            logger.exception("SDK execution observation failed")

    def begin(self, speech, snapshot: TurnSnapshot, *, context_id: str) -> SDKStep:
        if self._close_task is not None:
            raise RuntimeError("SDK execution bridge is closed")
        if speech is None:
            # A missing SDK identity must never be replaced with a mutable 'current run'.
            raise RuntimeError("SDK model request has no owning speech handle")
        previous = self._speeches.get(speech.id)
        if previous is None:
            if len(self._speeches) >= 128:
                raise RuntimeError("Too many active SDK speech owners")
            step = SDKStep(
                OutputScope(context_id, snapshot.turn_id, f"sdk:{speech.id}"), uuid4().hex, 1
            )
            self._runtime.output.activate_run(step.scope.run_id)
            previous = _Speech(step)
            self._speeches[speech.id] = previous
            self.signal(step, ExecutionSignalKind.ACCEPTED, "accepted")
            previous.watcher = asyncio.create_task(
                self._watch(speech, previous), name=f"sdk_speech:{speech.id}"
            )
        else:
            if (
                previous.step.scope.turn_id != snapshot.turn_id
                or previous.step.scope.context_id != context_id
            ):
                raise ValueError("SDK speech identity was reused across execution contexts")
            if not self._runtime.output.accepts_run(previous.step.scope.run_id):
                raise asyncio.CancelledError
            previous.step = replace(
                previous.step,
                request_id=uuid4().hex,
                model_step=previous.step.model_step + 1,
                commentary_output_ids=(),
            )
            previous.failure = None
        return previous.step

    def model_started(self, step: SDKStep) -> None:
        self.signal(step, ExecutionSignalKind.MODEL_STARTED, "model")

    def model_failed(self, step: SDKStep, *, cancelled: bool) -> None:
        state = self._speeches.get(step.scope.run_id.removeprefix("sdk:"))
        if state is not None and state.step.request_id == step.request_id:
            state.failure = "cancelled" if cancelled else "failed"

    def visible(self, step: SDKStep, output_id: str) -> None:
        speech_id = step.scope.run_id.removeprefix("sdk:")
        state = self._speeches.get(speech_id)
        if state is not None and state.step.request_id == step.request_id:
            ids = tuple(dict.fromkeys((*state.step.commentary_output_ids, output_id)))
            state.step = replace(state.step, commentary_output_ids=ids[-64:])

    def tool_step(self, context: RunContext) -> SDKStep | None:
        state = self._speeches.get(context.speech_handle.id)
        return state.step if state is not None else None

    async def _watch(self, speech, state: _Speech) -> None:
        outcome = "completed"
        try:
            await speech.wait_for_playout()
            outcome = "cancelled" if speech.interrupted else state.failure or "completed"
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except Exception:
            outcome = "failed"
            logger.exception("SDK speech observation failed")
        finally:
            self.signal(state.step, ExecutionSignalKind.FINISHED, outcome)
            if outcome != "completed":
                self._runtime.output.revoke_run(state.step.scope.run_id)
            self._speeches.pop(speech.id, None)

    async def _close(self) -> None:
        tasks = tuple(s.watcher for s in self._speeches.values() if s.watcher is not None)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._speeches.clear()

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="sdk_execution_close")
        await wait_for_cleanup(self._close_task)


def extract_answer_text(chunk) -> str | None:
    if isinstance(chunk, str):
        return chunk or None
    value = getattr(getattr(chunk, "delta", None), "content", None)
    return value if isinstance(value, str) and value else None
