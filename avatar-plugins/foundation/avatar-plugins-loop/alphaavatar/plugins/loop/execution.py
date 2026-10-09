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
from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import uuid4

from alphaavatar.agents.avatar.context.schemas import ContextPrepareRequest
from alphaavatar.agents.avatar.loop import LoopHandle
from alphaavatar.agents.avatar.loop.base import ToolAuthorizer
from alphaavatar.agents.avatar.loop.enums import LoopState, ToolOutcome
from alphaavatar.agents.avatar.loop.schemas import (
    LoopIdentity,
    LoopRequest,
    LoopResult,
)
from alphaavatar.agents.avatar.provider.enums import ModelMessagePhase, ModelRole
from alphaavatar.agents.avatar.provider.errors import ModelIncompleteError, ModelProtocolError
from alphaavatar.agents.avatar.provider.records import model_record_batch
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
from alphaavatar.core.output.enums import ExecutionSignalKind

from .config import RealtimeLoopConfig
from .feedback import LoopFeedback
from .policy import ExecutionBudget
from .tools import LoopTools

if TYPE_CHECKING:
    from alphaavatar.agents.avatar.provider.gateway import ProviderGateway
    from alphaavatar.agents.runtime import AvatarRuntime

logger = logging.getLogger(__name__)


class LoopCommitError(RuntimeError):
    """Output admission failed; never continue as though model records were retained."""


class LoopExecution(LoopHandle):
    def __init__(
        self,
        request: LoopRequest,
        config: RealtimeLoopConfig,
        *,
        runtime: AvatarRuntime,
        gateway: ProviderGateway,
        unsafe_lock: asyncio.Lock,
        authorize: ToolAuthorizer | None = None,
    ) -> None:
        self._identity = LoopIdentity(uuid4().hex, request.turn_id, request.context_id)
        self._request = request
        self._config = config
        self._runtime = runtime
        self._gateway = gateway
        self._context_manager = runtime.foundation.context
        self._budget = ExecutionBudget(request, asyncio.get_running_loop().time())
        self._items: list[ModelInputItem] = list(request.input.items)
        self._new_items: list[ModelInputItem] = []
        self._commits = 0
        self._pending_calls: tuple[ModelFunctionCall, ...] = ()
        self._context: ModelInput | None = None
        self._generation_options = self._budget.options(
            config.supported_reasoning_efforts, finalizing=False
        )
        self._cancel_reason: str | None = None
        self._started = False
        self._settled = False
        self._close_task: asyncio.Task[None] | None = None
        self._feedback = LoopFeedback(self.identity, runtime, timeout=config.feedback_timeout)
        self._tools = LoopTools(
            self.identity,
            runtime,
            self._budget,
            self._feedback,
            unsafe_lock,
            cancelled=lambda: self._cancel_reason is not None,
            policies=config.tool_policies,
            authorize=authorize,
        )
        self._definitions = self._tools.definitions
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
        self._runtime.output.revoke_run(self.identity.run_id)
        if self._started:
            self.task.cancel()

    async def wait(self) -> LoopResult:
        return await asyncio.shield(self.task)

    async def _commit(self, items: tuple[ModelInputItem, ...]) -> None:
        if not items:
            return

        existing = {item.id for item in self._items}
        if self._context is not None:
            existing.update(item.id for item in self._context.items)

        identities = {item.id for item in items}
        if len(identities) != len(items) or existing.intersection(identities):
            raise ModelProtocolError("Execution history contains duplicate item identities")

        calls = tuple(item for item in items if isinstance(item, ModelFunctionCall))
        if calls and self._pending_calls:
            raise ModelProtocolError("Previous tool calls have not been settled")

        # Freeze and admit atomically before changing local history or dispatching tools.
        records = tuple(
            replace(
                item, metadata={**item.metadata, "output_id": self._feedback.output_id(item.id)}
            )
            if isinstance(item, ModelInputMessage)
            else item
            for item in items
        )
        batch = model_record_batch(
            batch_id=f"loop:{self.identity.run_id}:{self._commits + 1}",
            source="avatar.loop",
            scope=self._feedback.scope,
            items=records,
        )
        if batch is not None:
            try:
                self._runtime.output.publish_records(batch)
            except Exception as exc:
                raise LoopCommitError("Output record batch was not accepted") from exc

        self._items.extend(items)
        self._new_items.extend(items)
        if calls:
            self._pending_calls = calls

        self._commits += 1

    async def _settle_pending(self, *, reason: str) -> None:
        if not self._pending_calls:
            return

        async def settle() -> None:
            calls = self._pending_calls
            records = self._tools.settle(calls, reason=reason)
            await self._commit(tuple(record.output for record in records))
            self._pending_calls = ()

        await wait_for_cleanup(asyncio.create_task(settle(), name="loop_call_settlement"))

    async def _model(self, *, finalizing: bool, reason: str | None) -> ModelResponseCompleted:
        if self._context is None:
            raise RuntimeError("Query context was not prepared")
        if self._pending_calls:
            raise ModelProtocolError("Unsettled calls cannot enter another model request")

        budget = self._budget
        tools_allowed = (
            not finalizing
            and budget.tool_rounds < self._request.limits.max_tool_rounds
            and budget.tool_calls < self._request.limits.max_tool_calls
        )
        options = self._generation_options
        if finalizing:
            options = options.model_copy(
                update={"max_output_tokens": self._request.limits.final_output_tokens}
            )
        request = ModelRequest(
            input=self._context_manager.build(self._context, continuation=tuple(self._new_items)),
            # Preserve schemas/order even when tool use is disabled for finalization.
            tools=self._definitions,
            tool_choice="auto" if tools_allowed and self._definitions else "none",
            parallel_tool_calls=(
                bool(self._definitions) and self._request.limits.max_parallel_tools > 1
            ),
            options=options,
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
        self._feedback.begin_model(request.request_id)
        await self._feedback.change(state, reason=reason)
        terminal = None
        partial: dict[str, tuple[ModelMessagePhase | None, dict[int, list[str]]]] = {}
        completed_messages: dict[str, ModelInputMessage] = {}
        order: dict[str, int] = {}
        try:
            async with self._gateway.stream(task_name="avatar.loop", request=request) as events:
                async for event in events:
                    if self._cancel_reason is not None:
                        raise asyncio.CancelledError
                    if event.request_id != request.request_id:
                        raise ModelProtocolError("Loop received another request's output")
                    if terminal is not None:
                        raise ModelProtocolError("Loop received output after completion")

                    if isinstance(event, ModelTextDelta):
                        order[event.item_id] = event.output_index
                        entry = partial.setdefault(event.item_id, (event.phase, {}))
                        entry[1].setdefault(event.content_index, []).append(event.text)
                        await self._feedback.text(event)
                    elif isinstance(event, ModelRefusalDelta):
                        pass  # Refusal is delivered as a complete typed message.
                    elif isinstance(event, ModelItemCompleted):
                        if not isinstance(event.item, ModelInputMessage):
                            continue
                        visible = replace(
                            event.item,
                            parts=tuple(
                                part
                                for part in event.item.parts
                                if isinstance(part, ModelTextPart | ModelRefusalPart)
                            ),
                        )
                        if visible.parts:
                            order[visible.id] = event.output_index
                            completed_messages[visible.id] = visible
                            await self._feedback.message(visible)
                    elif isinstance(event, ModelResponseCompleted):
                        terminal = event

            if terminal is None:
                raise ModelProtocolError("Loop model stream ended without completion")

            calls = tuple(item for item in terminal.items if isinstance(item, ModelFunctionCall))
            if request.tool_choice == "none" and calls:
                raise ModelProtocolError("Model returned tools when invocation was disabled")

            prior_calls = {
                item.call_id for item in self._items if isinstance(item, ModelFunctionCall)
            }
            call_ids = [item.call_id for item in calls]
            if len(set(call_ids)) != len(call_ids) or prior_calls.intersection(call_ids):
                raise ModelProtocolError("Model reused a tool call identity")
        except BaseException:
            # Complete visible messages include refusal/commentary; only truncated text is partial.
            visible = []
            for item_id in sorted(order, key=order.__getitem__):
                if item_id in completed_messages:
                    visible.append(completed_messages[item_id])
                elif item_id in partial:
                    phase, chunks = partial[item_id]
                    if chunks:
                        visible.append(
                            ModelInputMessage(
                                id=item_id,
                                role=ModelRole.ASSISTANT,
                                parts=tuple(
                                    ModelTextPart("".join(chunks[i])) for i in sorted(chunks)
                                ),
                                phase=phase,
                                interrupted=True,
                            )
                        )

            if visible:
                await self._commit(tuple(visible))

            await self._feedback.interrupt_incomplete("model_stream_stopped")
            raise

        for item in terminal.items:
            if isinstance(item, ModelInputMessage):
                await self._feedback.message(item)

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
                        budget.tool_rounds += 1
                        self._feedback.tool_round = budget.tool_rounds
                        await self._feedback.change(LoopState.TOOLS)
                        results = await self._tools.batch(calls)
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
            finally:
                await self._settle_pending(
                    reason=reason or self._cancel_reason or "execution_stopped"
                )

        if self._cancel_reason is not None:
            raise asyncio.CancelledError

        # One answer-only request, using the same prefix, tools and reasoning profile.
        async with asyncio.timeout_at(budget.deadline):
            response = await self._model(finalizing=True, reason=reason)

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
            async with asyncio.timeout_at(self._budget.exploration_deadline):
                preparation = ContextPrepareRequest(
                    input=self._request.input,
                    turn_id=self.identity.turn_id,
                    context_id=self.identity.context_id,
                    input_id=self._request.input_id,
                    contributions=(self._budget.contribution(),),
                )
                self._context = await self._context_manager.prepare(preparation)

            if not isinstance(self._context, ModelInput):
                raise TypeError("ContextManager.prepare must return ModelInput")
            if self._cancel_reason is not None:
                raise asyncio.CancelledError

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

        finally:
            try:
                await self._settle_pending(
                    reason=self._cancel_reason or reason or "execution_stopped"
                )
            except asyncio.CancelledError as exc:
                state, reason = LoopState.CANCELLED, self._cancel_reason or "cancelled"
                if exc.__cause__ is not None:
                    error_type = type(exc.__cause__).__name__
            except Exception as exc:
                state, reason, error_type = LoopState.FAILED, "history_failed", type(exc).__name__
                answers = ()

            try:
                await self._feedback.aclose(
                    interrupted=state
                    not in {
                        LoopState.COMPLETED,
                        LoopState.PARTIAL,
                        LoopState.REFUSED,
                    }
                )
            except asyncio.CancelledError:
                state, reason = LoopState.CANCELLED, self._cancel_reason or "cancelled"
            except Exception as exc:
                state, reason = LoopState.FAILED, "output_cleanup_failed"
                error_type = type(exc).__name__
                answers = ()
        if self._cancel_reason is not None:
            state, reason, answers = LoopState.CANCELLED, self._cancel_reason, ()

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
        self._feedback.signal(ExecutionSignalKind.FINISHED, reason=reason)
        return result

    async def aclose(self) -> None:
        if self._close_task is None:
            self.cancel(reason="closed")

            async def close() -> None:
                await asyncio.gather(self.task, return_exceptions=False)

            self._close_task = asyncio.create_task(close(), name="loop_execution_close")
        await wait_for_cleanup(self._close_task)
