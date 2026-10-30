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
from typing import TYPE_CHECKING
from uuid import uuid4

from alphaavatar.agents.avatar.context import ContextIdentityChanged
from alphaavatar.agents.avatar.context.schemas import ContextPrepareRequest
from alphaavatar.agents.avatar.loop import LoopHandle
from alphaavatar.agents.avatar.loop.base import ToolAuthorizer
from alphaavatar.agents.avatar.loop.enums import LoopState, ToolOutcome
from alphaavatar.agents.avatar.loop.schemas import LoopIdentity, LoopRequest, LoopResult
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
from alphaavatar.core.log.diagnostics import format_error
from alphaavatar.core.log.events import log_event
from alphaavatar.core.output.enums import ExecutionSignalKind

from .config import RealtimeLoopConfig
from .feedback import LoopFeedback
from .policy import ExecutionBudget
from .tools import LoopTools

if TYPE_CHECKING:
    from alphaavatar.agents.avatar.provider.gateway import ProviderGateway
    from alphaavatar.agents.runtime import AvatarRuntime
    from alphaavatar.core.turn.schemas import TurnSnapshot

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
        snapshot = runtime.turn.get(request.input_id)
        if snapshot is None or snapshot.turn_id != request.turn_id:
            raise ValueError("Execution requires its committed input")

        participants = runtime.participants
        identities = tuple(
            (actor.participant_id, actor.user_id, actor.identity_sequence)
            for actor in snapshot.actors
            if actor.participant_id is not None and actor.user_id is not None
        )

        def delivery_guard() -> bool:
            return all(
                (current := participants.get(participant_id)) is not None
                and current.user_id == user_id
                and current.identity_sequence == sequence
                and participants.accepts_identity(current)
                for participant_id, user_id, sequence in identities
            )

        self._delivery_guard = delivery_guard
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
        self._turn: TurnSnapshot = snapshot
        self._generation_options = self._budget.options(config.reasoning, finalizing=False)
        self._cancel_reason: str | None = None
        self._started = False
        self._settled = False
        self._close_task: asyncio.Task[None] | None = None
        self._feedback = LoopFeedback(
            self.identity,
            runtime,
            timeout=config.feedback_timeout,
            reasoning_effort=self._generation_options.reasoning_effort,
            query_difficulty=request.query_difficulty,
        )
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

    @property
    def delivery_guard(self) -> Callable[[], bool]:
        return self._delivery_guard

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
        for item in items:
            if (
                batch is not None
                and isinstance(item, ModelInputMessage)
                and item.role == ModelRole.ASSISTANT
                and any(isinstance(part, ModelTextPart | ModelRefusalPart) for part in item.parts)
            ):
                self._log(
                    "assistant.message",
                    item_id=item.id,
                    output_id=self._feedback.output_id(item.id),
                    stage="recorded",
                    model_step=self._budget.model_steps,
                    phase=item.phase.value if item.phase is not None else "unspecified",
                    interrupted=item.interrupted,
                    refusal=any(isinstance(part, ModelRefusalPart) for part in item.parts),
                    text_parts=(
                        part.text
                        for part in item.parts
                        if isinstance(part, ModelTextPart | ModelRefusalPart)
                    ),
                )

    async def _settle_pending(self, *, reason: str) -> None:
        if not self._pending_calls:
            return

        async def settle() -> None:
            calls = self._pending_calls
            records = self._tools.settle(calls, reason=reason)
            await self._commit(tuple(record.output for record in records))
            self._pending_calls = ()

        await wait_for_cleanup(asyncio.create_task(settle(), name="loop_call_settlement"))

    def _check_identity(self) -> None:
        if not self._delivery_guard():
            raise ContextIdentityChanged("Execution identity changed")

    async def _watch_identity(self) -> None:
        stream = self._runtime.session.events
        consumer_id = f"loop.identity:{self.identity.run_id}"
        try:
            while True:
                sequence = stream.latest_sequence
                if not self._delivery_guard():
                    self.cancel(reason="identity_changed")
                    return
                # This consumer observes current state only; version checks also detect ABA/gaps.
                stream.commit(consumer_id=consumer_id, cursor_seq=sequence)
                if not await stream.wait_for_pending(consumer_id=consumer_id):
                    return
        finally:
            stream.clear_consumer(consumer_id)

    async def _model(self, *, finalizing: bool, reason: str | None) -> ModelResponseCompleted:
        self._check_identity()
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
        started_at = asyncio.get_running_loop().time()
        first_event_ms: float | None = None
        first_text_ms: float | None = None
        first_text = False
        self._log(
            "model.started",
            request_id=request.request_id,
            backend=self._config.model.backend,
            provider=self._config.model.provider,
            model=self._config.model.model,
            requested_reasoning_effort=options.reasoning_effort,
            query_difficulty=self._request.query_difficulty,
            model_step=budget.model_steps,
            state=state.value,
        )
        terminal = None
        order: dict[str, int] = {}
        try:
            self._check_identity()
            async with self._gateway.stream(task_name="avatar.loop", request=request) as events:
                async for event in events:
                    self._check_identity()
                    if self._cancel_reason is not None:
                        raise asyncio.CancelledError
                    if event.request_id != request.request_id:
                        raise ModelProtocolError("Loop received another request's output")
                    if terminal is not None:
                        raise ModelProtocolError("Loop received output after completion")

                    if first_event_ms is None:
                        first_event_ms = (asyncio.get_running_loop().time() - started_at) * 1000
                        self._log(
                            "model.first_event",
                            request_id=request.request_id,
                            event_kind=type(event).__name__,
                            elapsed_ms=first_event_ms,
                        )

                    if isinstance(event, ModelTextDelta):
                        if not first_text and event.text:
                            first_text = True
                            first_text_ms = (asyncio.get_running_loop().time() - started_at) * 1000
                            self._log(
                                "model.first_text",
                                request_id=request.request_id,
                                response_id=event.response_id,
                                elapsed_ms=first_text_ms,
                            )
                        order[event.item_id] = event.output_index
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
                            await self._feedback.message(visible)
                    elif isinstance(event, ModelResponseCompleted):
                        terminal = event

            self._check_identity()
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

            for index, item in enumerate(terminal.items):
                if isinstance(item, ModelInputMessage):
                    self._check_identity()
                    order.setdefault(item.id, index)
                    await self._feedback.message(item)

            self._check_identity()
            await self._commit(terminal.items)
            if self._cancel_reason is not None:
                raise asyncio.CancelledError
        except BaseException:
            # Keep locally admitted output, including cancellation during subscriber backpressure.
            recorded = {item.id for item in self._items}
            admitted = tuple(
                message
                for item_id in sorted(order, key=order.__getitem__)
                if item_id not in recorded
                if (message := self._feedback.accepted_message(item_id)) is not None
            )
            if admitted:
                await self._commit(admitted)

            await self._feedback.interrupt_incomplete("model_stream_stopped")
            raise

        self._log(
            "model.completed",
            request_id=request.request_id,
            response_id=terminal.response_id,
            model_step=budget.model_steps,
            output_items=len(terminal.items),
            requested_reasoning_effort=options.reasoning_effort,
            query_difficulty=self._request.query_difficulty,
            first_event_ms=first_event_ms,
            first_visible_text_ms=first_text_ms,
            input_tokens=terminal.usage.input_tokens if terminal.usage else None,
            output_tokens=terminal.usage.output_tokens if terminal.usage else None,
            reasoning_output_tokens=terminal.usage.reasoning_output_tokens
            if terminal.usage
            else None,
            cached_input_tokens=terminal.usage.cached_input_tokens if terminal.usage else None,
            elapsed_ms=(asyncio.get_running_loop().time() - started_at) * 1000,
        )
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

    def _log(self, name: str, **fields) -> None:
        log_event(
            logger,
            name,
            session_id=self._runtime.session.session_id,
            context_id=self.identity.context_id,
            turn_id=self.identity.turn_id,
            run_id=self.identity.run_id,
            **fields,
        )

    def _diagnose(self, error: BaseException, *, stage: str) -> None:
        # Keep exception chains and code locations, never prompts, payloads or tool arguments.
        logger.warning(
            "Avatar loop failed run_id=%s stage=%s\n%s",
            self.identity.run_id,
            stage,
            format_error(error, details=True),
        )

    async def _run(self) -> LoopResult:
        self._started = True
        state = LoopState.FAILED
        answers: tuple[ModelInputMessage, ...] = ()
        reason = error_type = None
        stage = "prepare_context"
        identity_watch = None
        try:
            if self._cancel_reason is not None:
                raise asyncio.CancelledError

            await self._feedback.change(LoopState.ACCEPTED)
            self._log("run.started", input_id=self._request.input_id, state="accepted")
            snapshot = self._turn
            if any(actor.user_id is not None for actor in snapshot.actors):
                identity_watch = asyncio.create_task(
                    self._watch_identity(), name=f"loop_identity:{self.identity.run_id}"
                )

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

            stage = "model_and_tools"
            state, answers, reason = await self._drive()
        except ContextIdentityChanged:
            self._runtime.output.revoke_run(self.identity.run_id)
            state, reason = LoopState.CANCELLED, "identity_changed"
        except asyncio.CancelledError as exc:
            state, reason = LoopState.CANCELLED, self._cancel_reason or "cancelled"
            if exc.__cause__ is not None:
                error_type = type(exc.__cause__).__name__
                self._diagnose(exc, stage=stage)
        except Exception as exc:
            error_type = type(exc).__name__
            reason = "timeout" if isinstance(exc, TimeoutError) else "execution_failed"
            self._diagnose(exc, stage=stage)

        finally:
            if identity_watch is not None:
                identity_watch.cancel()
                await asyncio.gather(identity_watch, return_exceptions=True)
            try:
                await self._settle_pending(
                    reason=self._cancel_reason or reason or "execution_stopped"
                )
            except asyncio.CancelledError as exc:
                state, reason = LoopState.CANCELLED, self._cancel_reason or "cancelled"
                if exc.__cause__ is not None:
                    error_type = type(exc.__cause__).__name__
                    self._diagnose(exc, stage="record_settlement")
            except Exception as exc:
                state, reason, error_type = LoopState.FAILED, "history_failed", type(exc).__name__
                answers = ()
                self._diagnose(exc, stage="record_settlement")

            try:
                await self._feedback.aclose(
                    interrupted=state
                    not in {LoopState.COMPLETED, LoopState.PARTIAL, LoopState.REFUSED}
                )
            except asyncio.CancelledError:
                state, reason = LoopState.CANCELLED, self._cancel_reason or "cancelled"
            except Exception as exc:
                state, reason = LoopState.FAILED, "output_cleanup_failed"
                error_type = type(exc).__name__
                answers = ()
                self._diagnose(exc, stage="output_cleanup")

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
        self._log(
            "run.finished",
            state=state.value,
            reason=reason,
            error_type=error_type,
            model_steps=result.model_steps,
            tool_rounds=result.tool_rounds,
            elapsed_ms=result.elapsed_ms,
            level=logging.WARNING if error_type is not None else logging.INFO,
        )
        return result

    async def aclose(self) -> None:
        if self._close_task is None:
            self.cancel(reason="closed")

            async def close() -> None:
                await asyncio.gather(self.task, return_exceptions=False)

            self._close_task = asyncio.create_task(close(), name="loop_execution_close")
        await wait_for_cleanup(self._close_task)
