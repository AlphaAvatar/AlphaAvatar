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
import hashlib
import json
import logging
import time
from collections.abc import Callable, Mapping
from math import isfinite
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from pydantic import BaseModel

from alphaavatar.agents.avatar.loop.base import ToolAuthorizer
from alphaavatar.agents.avatar.loop.enums import LoopEventKind, ToolOutcome
from alphaavatar.agents.avatar.loop.schemas import (
    LoopIdentity,
    ToolCallContext,
    ToolRecord,
)
from alphaavatar.agents.avatar.provider.schemas import (
    ModelFunctionCall,
    ModelFunctionOutput,
    ModelMediaPart,
    ModelTextPart,
    ModelToolDefinition,
)
from alphaavatar.agents.runtime.capability.result import CapabilityResult
from alphaavatar.core.cleanup import wait_for_cleanup

from .config import ToolPolicy
from .feedback import LoopFeedback
from .policy import ExecutionBudget

if TYPE_CHECKING:
    from alphaavatar.agents.runtime import AvatarRuntime

logger = logging.getLogger(__name__)


class ToolInputError(ValueError):
    pass


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ToolInputError("Duplicate argument key")
        result[key] = value
    return result


def _constant(value: str) -> Any:
    raise ToolInputError(f"Non-finite JSON number: {value}")


def _number(value: str) -> float:
    number = float(value)
    if not isfinite(number):
        raise ToolInputError("Non-finite JSON number")
    return number


def parse_arguments(value: str, *, max_bytes: int) -> dict[str, Any]:
    if len(value.encode("utf-8")) > max_bytes:
        raise ToolInputError("Tool arguments exceed the execution limit")
    try:
        result = json.loads(
            value, object_pairs_hook=_object, parse_constant=_constant, parse_float=_number
        )
    except (ValueError, RecursionError) as exc:
        raise ToolInputError("Expected finite JSON arguments with unique keys") from exc
    if not isinstance(result, dict):
        raise ToolInputError("Tool arguments must be a JSON object")
    return result


def result_parts(value: Any, *, max_bytes: int) -> tuple[tuple[Any, ...], bool]:
    if isinstance(value, CapabilityResult):
        parts, is_error = value.parts, value.is_error
    else:
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json", by_alias=True)
        text = value if isinstance(value, str) else json.dumps(value, allow_nan=False)
        parts, is_error = (ModelTextPart(text),), False

    size = 0
    for part in parts:
        if isinstance(part, ModelTextPart):
            size += len(part.text.encode("utf-8"))
        elif isinstance(part, ModelMediaPart):
            size += len(part.data or b"") + len((part.uri or "").encode("utf-8"))
        else:
            raise TypeError("Tool results must use explicit text or media parts")
    if size > max_bytes:
        raise ValueError("Tool result exceeds the execution limit")
    return tuple(parts), is_error


class LoopTools:
    """Scheduling and call records only. Invocation always uses the existing registry."""

    def __init__(
        self,
        identity: LoopIdentity,
        runtime: AvatarRuntime,
        budget: ExecutionBudget,
        feedback: LoopFeedback,
        unsafe_lock: asyncio.Lock,
        cancelled: Callable[[], bool],
        *,
        policies: Mapping[str, ToolPolicy],
        authorize: ToolAuthorizer | None,
    ) -> None:
        self._identity = identity
        self._registry = runtime.capability_registry
        self._authorize = authorize
        self._budget = budget
        self._feedback = feedback
        self._unsafe_lock = unsafe_lock
        self._cancelled = cancelled

        allowed = set(budget.request.allowed_capabilities)
        capabilities = {c.id: c for c in self._registry.capabilities if c.callable}
        if unknown := allowed - capabilities.keys():
            raise ValueError(f"Unknown or description-only capabilities: {sorted(unknown)}")
        self._capabilities = {capabilities[name].tool_name: capabilities[name] for name in allowed}

        self._policies = dict(policies)
        self._signatures: dict[str, int] = {}
        self._records: dict[str, ToolRecord] = {}
        self.records: list[ToolRecord] = []

    @property
    def definitions(self) -> tuple[ModelToolDefinition, ...]:
        return tuple(
            ModelToolDefinition(
                name=c.tool_name, description=c.description, parameters=c.parameters
            )
            for c in sorted(self._capabilities.values(), key=lambda c: c.id)
        )

    def _stopping(self) -> bool:
        task = asyncio.current_task()
        return self._cancelled() or bool(task is not None and task.cancelling())

    def _policy(self, call: ModelFunctionCall) -> ToolPolicy:
        capability = self._capabilities.get(call.name)
        return self._policies.get(capability.id, ToolPolicy()) if capability else ToolPolicy()

    def _record(
        self,
        call: ModelFunctionCall,
        outcome: ToolOutcome,
        *,
        executed: bool,
        started: float,
        code: str | None = None,
        parts: tuple[Any, ...] | None = None,
        is_error: bool = True,
    ) -> ToolRecord:
        if parts is None:
            content = {"status": outcome.value, "code": code, "executed": executed}
            if outcome == ToolOutcome.UNKNOWN:
                content["warning"] = "The external action may have completed; do not retry blindly."
            parts = (ModelTextPart(json.dumps(content, separators=(",", ":"))),)
        record = ToolRecord(
            call=call,
            output=ModelFunctionOutput(
                id=f"tool_result:{uuid4().hex}",
                call_id=call.call_id,
                name=call.name,
                parts=parts,
                is_error=is_error,
            ),
            outcome=outcome,
            executed=executed,
            duration_ms=(time.perf_counter() - started) * 1000,
        )
        self._records[call.call_id] = record
        return record

    async def _invoke(self, call: ModelFunctionCall) -> ToolRecord:
        started = time.perf_counter()
        limits = self._budget.request.limits
        executed = False
        policy = self._policy(call)
        try:
            if self._stopping():
                raise asyncio.CancelledError

            capability = self._capabilities.get(call.name)
            if capability is None:
                return self._record(
                    call, ToolOutcome.DENIED, executed=False, started=started, code="not_allowed"
                )

            payload = parse_arguments(call.arguments, max_bytes=limits.max_arguments_bytes)

            # Validate before authorization and before obtaining the side-effect execution slot.
            capability.parse(payload)
            signature = hashlib.sha256(
                json.dumps([capability.id, payload], sort_keys=True, allow_nan=False).encode()
            ).hexdigest()
            count = self._signatures.get(signature, 0)
            if count >= limits.max_same_call:
                return self._record(
                    call, ToolOutcome.SKIPPED, executed=False, started=started, code="repeat_limit"
                )
            self._signatures[signature] = count + 1
            authorizer = self._authorize
            if authorizer is not None:
                approved = await authorizer(ToolCallContext(self._identity, call, capability.id))
                if not isinstance(approved, bool):
                    raise TypeError("Tool authorizers must return bool")
            else:
                approved = policy.read_only and not policy.approval_required

            if not approved:
                return self._record(
                    call,
                    ToolOutcome.DENIED,
                    executed=False,
                    started=started,
                    code="approval_required",
                )

            async def execute() -> Any:
                nonlocal executed
                await self._feedback.emit(
                    LoopEventKind.TOOL_STARTED, call_id=call.call_id, tool_name=call.name
                )
                if self._stopping():
                    raise asyncio.CancelledError
                if asyncio.get_running_loop().time() >= self._budget.exploration_deadline:
                    raise TimeoutError("Tool dispatch deadline expired")
                executed = True
                return await self._registry.invoke(call.name, payload)

            remaining = self._budget.exploration_deadline - asyncio.get_running_loop().time()
            async with asyncio.timeout(min(limits.tool_timeout, max(0, remaining))):
                if policy.read_only:
                    raw = await execute()
                else:
                    # Serialize local write dispatch across foreground and retiring executions.
                    async with self._unsafe_lock:
                        raw = await execute()
            try:
                parts, is_error = result_parts(raw, max_bytes=limits.max_result_bytes)
            except (ValueError, TypeError, RecursionError):
                return self._record(
                    call,
                    ToolOutcome.UNKNOWN,
                    executed=True,
                    started=started,
                    code="result_not_representable",
                )
            return self._record(
                call,
                ToolOutcome.FAILED if is_error else ToolOutcome.SUCCEEDED,
                executed=True,
                started=started,
                parts=parts,
                is_error=is_error,
            )
        except asyncio.CancelledError:
            uncertain = executed and not policy.read_only
            return self._record(
                call,
                ToolOutcome.UNKNOWN if uncertain else ToolOutcome.CANCELLED,
                executed=executed,
                started=started,
                code="cancelled",
            )
        except TimeoutError:
            return self._record(
                call,
                ToolOutcome.FAILED if policy.read_only or not executed else ToolOutcome.UNKNOWN,
                executed=executed,
                started=started,
                code="timeout",
            )
        except Exception as exc:
            return self._record(
                call,
                ToolOutcome.FAILED if policy.read_only or not executed else ToolOutcome.UNKNOWN,
                executed=executed,
                started=started,
                code="invalid_arguments" if not executed else type(exc).__name__,
            )

    async def _run_call(self, call: ModelFunctionCall) -> ToolRecord:
        record = await self._invoke(call)
        try:
            await self._feedback.emit(
                LoopEventKind.TOOL_FINISHED,
                call_id=call.call_id,
                tool_name=call.name,
                outcome=record.outcome,
            )
        except asyncio.CancelledError:
            pass  # The execution owner still commits the already recorded tool fact.
        except Exception:
            logger.exception("Tool completion feedback failed")
        return record

    def settle(
        self, calls: tuple[ModelFunctionCall, ...], *, reason: str
    ) -> tuple[ToolRecord, ...]:
        """Reconcile accepted calls even when execution never entered batch()."""
        known = {record.call.call_id for record in self.records}
        ordered = []
        for call in calls:
            if call.call_id not in self._records:
                self._record(
                    call,
                    ToolOutcome.SKIPPED,
                    executed=False,
                    started=time.perf_counter(),
                    code=reason,
                )
            record = self._records[call.call_id]
            ordered.append(record)
            if call.call_id not in known:
                self.records.append(record)
                known.add(call.call_id)
        return tuple(ordered)

    async def batch(self, calls: tuple[ModelFunctionCall, ...]) -> tuple[ToolRecord, ...]:
        identities = [call.call_id for call in calls]
        if len(set(identities)) != len(identities) or any(i in self._records for i in identities):
            raise ValueError("Repeated call identity must never execute twice")

        tasks: list[asyncio.Task[ToolRecord]] = []
        active: list[asyncio.Task[ToolRecord]] = []
        try:
            for call in calls:
                if self._stopping():
                    raise asyncio.CancelledError

                budget = self._budget
                if budget.tool_calls >= budget.request.limits.max_tool_calls:
                    self._record(
                        call,
                        ToolOutcome.SKIPPED,
                        executed=False,
                        started=time.perf_counter(),
                        code="tool_call_budget",
                    )
                    continue

                budget.tool_calls += 1
                policy = self._policy(call)
                parallel = policy.read_only and policy.parallel_safe
                at_capacity = len(active) >= budget.request.limits.max_parallel_tools
                if active and (not parallel or at_capacity):
                    await asyncio.shield(asyncio.gather(*active))
                    active.clear()
                if self._stopping():
                    raise asyncio.CancelledError
                task = asyncio.create_task(self._run_call(call), name=f"loop_tool:{call.call_id}")
                tasks.append(task)
                active.append(task)
                if not parallel:
                    await asyncio.shield(task)
                    active.clear()
            if active:
                await asyncio.shield(asyncio.gather(*active))

        finally:

            async def finish() -> None:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

            await wait_for_cleanup(asyncio.create_task(finish(), name="loop_tool_batch_close"))

        # The execution owner commits all results, including unstarted/cancelled calls.
        return self.settle(calls, reason="execution_stopped")
