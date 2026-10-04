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
from collections.abc import Callable
from dataclasses import replace
from uuid import uuid4

from alphaavatar.agents.avatar.loop import LoopDependencies, LoopHandle
from alphaavatar.agents.avatar.loop.enums import LoopEventKind, LoopState, ToolOutcome
from alphaavatar.agents.avatar.loop.schemas import (
    LoopCommit,
    LoopIdentity,
    LoopRequest,
    LoopResult,
)
from alphaavatar.agents.avatar.provider.enums import ModelMessagePhase, ModelRole
from alphaavatar.agents.avatar.provider.errors import ModelIncompleteError, ModelProtocolError
from alphaavatar.agents.avatar.provider.schemas import (
    ModelFunctionCall,
    ModelInput,
    ModelInputMessage,
    ModelRefusalPart,
    ModelRequest,
    ModelTextPart,
)
from alphaavatar.agents.avatar.provider.schemas.model_input import ModelInputItem
from alphaavatar.agents.avatar.provider.schemas.stream import (
    ModelItemCompleted,
    ModelRefusalDelta,
    ModelResponseCompleted,
    ModelTextDelta,
)
from alphaavatar.core.cleanup import wait_for_cleanup

from .config import RealtimeLoopConfig
from .feedback import LoopFeedback
from .policy import ExecutionBudget
from .tools import LoopTools

logger = logging.getLogger(__name__)


class LoopExecution(LoopHandle):
    def __init__(
        self,
        request: LoopRequest,
        config: RealtimeLoopConfig,
        dependencies: LoopDependencies,
        unsafe_lock: asyncio.Lock,
        is_current: Callable[[str], bool],
    ) -> None:
        self._commits = 0
        self._request = request
        self._config = config
        self._dependencies = dependencies

        self._items: list[ModelInputItem] = list(request.input.items)
        self._new_items: list[ModelInputItem] = []

        self._identity = LoopIdentity(uuid4().hex, request.turn_id, request.context_id)
        self._budget = ExecutionBudget(request, asyncio.get_running_loop().time())
        self._feedback = LoopFeedback(
            self.identity,
            dependencies.on_event,
            lambda: self._cancel_reason is None and is_current(self.identity.run_id),
            delay=config.feedback_delay,
            timeout=config.feedback_timeout,
        )
        self._tools = LoopTools(
            self.identity,
            dependencies,
            self._budget,
            self._feedback,
            unsafe_lock,
            cancelled=lambda: self._cancel_reason is not None,
        )

        self._started = False
        self._settled = False
        self._cancel_reason: str | None = None
        self._close_task: asyncio.Task[None] | None = None
        self.task = asyncio.create_task(self._run(), name=f"avatar_loop:{self.identity.run_id}")
        self.task.add_done_callback(self._observe)

    @property
    def identity(self) -> LoopIdentity:
        return self._identity

    @staticmethod
    def _observe(task: asyncio.Task[LoopResult]) -> None:
        if not task.cancelled():
            task.exception()

    @staticmethod
    def _answers(response: ModelResponseCompleted) -> tuple[ModelInputMessage, ...]:
        return tuple(
            replace(
                item,
                parts=tuple(
                    part
                    for part in item.parts
                    if isinstance(part, ModelTextPart | ModelRefusalPart)
                ),
            )
            for item in response.items
            if isinstance(item, ModelInputMessage)
            and item.phase != ModelMessagePhase.COMMENTARY
            and any(
                isinstance(part, ModelTextPart | ModelRefusalPart) and part.text.strip()
                for part in item.parts
            )
        )

    def cancel(self, *, reason: str = "interrupted") -> None:
        if self.task.done() or self._settled or self._cancel_reason is not None:
            return
        self._cancel_reason = reason
        if self._started:
            self.task.cancel()

    async def wait(self) -> LoopResult:
        return await asyncio.shield(self.task)

    async def _commit(self, items: tuple[ModelInputItem, ...]) -> None:
        if not items:
            return

        existing = {item.id for item in self._items}
        identities = {item.id for item in items}
        if len(identities) != len(items) or existing.intersection(identities):
            raise ModelProtocolError("Execution history contains duplicate item identities")

        self._items.extend(items)
        self._new_items.extend(items)
        self._commits += 1
        if self._dependencies.commit is not None:
            await self._dependencies.commit(
                LoopCommit(self.identity, f"{self.identity.run_id}:{self._commits}", items)
            )

    async def _model(self, *, finalizing: bool, reason: str | None) -> ModelResponseCompleted:
        budget = self._budget
        policy = budget.context(self.identity.run_id, finalizing=finalizing, reason=reason)
        tools_allowed = (
            not finalizing
            and budget.tool_rounds < self._request.limits.max_tool_rounds
            and budget.tool_calls < self._request.limits.max_tool_calls
        )

        request = ModelRequest(
            input=ModelInput(items=(*self._items, policy), realtime=self._request.input.realtime),
            tools=self._tools.definitions if tools_allowed else (),
            tool_choice="auto" if tools_allowed and self._tools.definitions else "none",
            parallel_tool_calls=tools_allowed and self._request.limits.max_parallel_tools > 1,
            options=budget.options(
                self._dependencies.supported_reasoning_efforts, finalizing=finalizing
            ),
            metadata={
                **self._request.metadata,
                "run_id": self.identity.run_id,
                "turn_id": self.identity.turn_id,
                "context_id": self.identity.context_id,
            },
        )

        budget.model_steps += 1
        self._feedback.model_step = budget.model_steps
        self._feedback.tool_round = budget.tool_rounds
        state = LoopState.FINALIZING if finalizing else LoopState.MODEL

        await self._feedback.change(state, reason=reason)

        terminal = None
        partial: dict[str, tuple[ModelMessagePhase | None, dict[int, list[str]]]] = {}
        completed_messages: dict[str, ModelInputMessage] = {}
        try:
            async with self._dependencies.provider.stream(
                self._config.model, request, trace=self._config.trace, task_name="avatar.loop"
            ) as events:
                async for event in events:
                    if self._cancel_reason is not None:
                        raise asyncio.CancelledError

                    if event.request_id != request.request_id:
                        raise ModelProtocolError("Loop received another request's output")

                    if terminal is not None:
                        raise ModelProtocolError("Loop received output after completion")

                    if isinstance(event, ModelTextDelta):
                        entry = partial.setdefault(event.item_id, (event.phase, {}))
                        entry[1].setdefault(event.content_index, []).append(event.text)
                        await self._feedback.visible(LoopEventKind.TEXT, text=event)
                    elif isinstance(event, ModelRefusalDelta):
                        # Refusal is delivered as a completed message, not ordinary answer tokens.
                        pass
                    elif isinstance(event, ModelItemCompleted):
                        if not isinstance(event.item, ModelInputMessage):
                            continue

                        completed_messages[event.item.id] = event.item
                        visible_message = replace(
                            event.item,
                            parts=tuple(
                                part
                                for part in event.item.parts
                                if isinstance(part, ModelTextPart | ModelRefusalPart)
                            ),
                        )
                        if visible_message.parts:
                            await self._feedback.visible(
                                LoopEventKind.MESSAGE, message=visible_message
                            )
                    elif isinstance(event, ModelResponseCompleted):
                        terminal = event

            if terminal is None:
                raise ModelProtocolError("Loop model stream ended without completion")

        except BaseException:
            # Preserve only visible partial text, never incomplete calls or opaque reasoning.
            visible = tuple(
                replace(completed_messages[item_id], interrupted=True)
                if item_id in completed_messages
                else ModelInputMessage(
                    id=item_id,
                    role=ModelRole.ASSISTANT,
                    parts=tuple(ModelTextPart("".join(chunks[i])) for i in sorted(chunks)),
                    phase=phase,
                    interrupted=True,
                )
                for item_id, (phase, chunks) in partial.items()
                if chunks
            )
            if visible:
                await wait_for_cleanup(
                    asyncio.create_task(self._commit(visible), name="loop_partial_history")
                )
            raise

        calls = [item for item in terminal.items if isinstance(item, ModelFunctionCall)]
        if request.tool_choice == "none" and calls:
            raise ModelProtocolError("Model returned tools when invocation was disabled")

        prior_calls = {item.call_id for item in self._items if isinstance(item, ModelFunctionCall)}
        call_ids = [item.call_id for item in calls]

        if len(set(call_ids)) != len(call_ids) or prior_calls.intersection(call_ids):
            raise ModelProtocolError("Model reused a tool call identity")

        await self._commit(terminal.items)

        if self._cancel_reason is not None:
            raise asyncio.CancelledError

        return terminal

    async def _drive(self) -> tuple[LoopState, tuple[ModelInputMessage, ...], str | None]:
        budget = self._budget
        reason = None
        while reason is None:
            if self._cancel_reason is not None:
                raise asyncio.CancelledError

            reason = budget.should_finalize(asyncio.get_running_loop().time())
            if reason is not None:
                break

            try:
                async with asyncio.timeout_at(budget.exploration_deadline):
                    response = await self._model(finalizing=False, reason=None)
                    calls = tuple(
                        item for item in response.items if isinstance(item, ModelFunctionCall)
                    )
                    if calls:
                        if budget.tool_rounds >= self._request.limits.max_tool_rounds:
                            raise ModelProtocolError("Model called tools when they were disabled")

                        budget.tool_rounds += 1
                        self._feedback.tool_round = budget.tool_rounds

                        await self._feedback.change(LoopState.TOOLS)
                        results = await self._tools.batch(calls, self._commit)

                        progressed = any(r.outcome == ToolOutcome.SUCCEEDED for r in results)
                        budget.no_progress = 0 if progressed else budget.no_progress + 1
                    elif answers := self._answers(response):
                        refused = any(
                            isinstance(part, ModelRefusalPart)
                            for answer in answers
                            for part in answer.parts
                        )
                        return LoopState.REFUSED if refused else LoopState.COMPLETED, answers, None
                    else:
                        budget.no_progress += 1
            except TimeoutError:
                reason = "time_budget"
            except ModelIncompleteError:
                reason = "incomplete_response"

        if self._cancel_reason is not None:
            raise asyncio.CancelledError

        # Exactly one answer-only request has a separate reserved slice of the same total budget.
        async with asyncio.timeout_at(budget.deadline):
            response = await self._model(finalizing=True, reason=reason)

        if any(isinstance(item, ModelFunctionCall) for item in response.items):
            raise ModelProtocolError("Answer-only request returned a new tool call")

        answers = self._answers(response)
        if not answers:
            return LoopState.PARTIAL, (), "no_final_answer"

        refused = any(isinstance(p, ModelRefusalPart) for a in answers for p in a.parts)
        return LoopState.REFUSED if refused else LoopState.PARTIAL, answers, reason

    async def _run(self) -> LoopResult:
        self._started = True
        state = LoopState.FAILED
        answers: tuple[ModelInputMessage, ...] = ()
        reason = error_type = None

        try:
            if self._cancel_reason is not None:
                raise asyncio.CancelledError

            await self._feedback.change(LoopState.ACCEPTED)
            state, answers, reason = await self._drive()
        except asyncio.CancelledError as exc:
            state, reason = LoopState.CANCELLED, self._cancel_reason or "cancelled"
            if exc.__cause__ is not None:
                error_type = type(exc.__cause__).__name__
        except Exception as exc:
            error_type = type(exc).__name__
            reason = "timeout" if isinstance(exc, TimeoutError) else "execution_failed"
            logger.warning(
                "Avatar loop failed run_id=%s error=%s", self.identity.run_id, error_type
            )

        try:
            await self._feedback.aclose()
        except asyncio.CancelledError:
            state, reason = LoopState.CANCELLED, self._cancel_reason or "cancelled"

        if self._cancel_reason is not None:
            state, reason = LoopState.CANCELLED, self._cancel_reason
            answers = ()

        self._settled = True
        result = LoopResult(
            identity=self.identity,
            state=state,
            items=tuple(self._new_items),
            final_messages=answers,
            tools=tuple(self._tools.records),
            model_steps=self._budget.model_steps,
            tool_rounds=self._budget.tool_rounds,
            elapsed_ms=(asyncio.get_running_loop().time() - self._budget.started_at) * 1000,
            reason=reason,
            error_type=error_type,
        )
        self._feedback.state = state

        try:
            await self._feedback.emit(LoopEventKind.FINISHED, reason=reason)
        except Exception:
            logger.exception("Loop terminal feedback failed")

        return result

    async def aclose(self) -> None:
        if self._close_task is None:
            self.cancel(reason="closed")

            async def close() -> None:
                await asyncio.gather(self.task, return_exceptions=False)

            self._close_task = asyncio.create_task(close(), name="loop_execution_close")

        await wait_for_cleanup(self._close_task)
