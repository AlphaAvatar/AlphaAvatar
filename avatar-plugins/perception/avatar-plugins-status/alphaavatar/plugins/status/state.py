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
from collections import OrderedDict
from dataclasses import dataclass

from alphaavatar.core.output.enums import ExecutionSignalKind
from alphaavatar.core.output.schemas import OutputExecutionSignal, OutputScope


@dataclass(frozen=True, slots=True)
class ActivityNotice:
    source_event_id: str
    scope: OutputScope
    action: str
    state: str
    revision: int
    tool_name: str | None = None
    outcome: str | None = None
    narration_key: str | None = None


@dataclass(slots=True)
class RunActivity:
    scope: OutputScope
    revision: int = 0
    request_id: str | None = None
    visible: bool = False
    finished: bool = False


class StatusState:
    """Processor-local observations, never the execution's source of truth."""

    def __init__(self, *, max_pending: int, max_runs: int) -> None:
        self.pending: asyncio.Queue[ActivityNotice] = asyncio.Queue(maxsize=max_pending)
        self.changed = asyncio.Event()
        self._runs: OrderedDict[str, RunActivity] = OrderedDict()
        self._max_runs = max_runs
        self._revision = 0
        self.current_run: str | None = None
        self.current_turn: str | None = None
        self._turn_time = -1
        self.dropped = 0

    def _next(self) -> int:
        self._revision += 1
        self.changed.set()
        return self._revision

    def current(self, scope: OutputScope, revision: int) -> bool:
        if scope.run_id is None:
            return self.current_turn is None and revision == self._revision
        state = self._runs.get(scope.run_id)
        return (
            self.current_run == scope.run_id
            and self.current_turn == scope.turn_id
            and state is not None
            and state.scope == scope
            and state.revision == revision
        )

    def offer(self, notice: ActivityNotice) -> None:
        if self.pending.full():
            self.pending.get_nowait()
            self.dropped += 1

        self.pending.put_nowait(notice)

    def turn(self, *, turn_id: str, context_id: str, at_ns: int, event_id: str) -> None:
        if at_ns < self._turn_time or turn_id == self.current_turn:
            return
        self._turn_time = at_ns
        self.current_turn, self.current_run = turn_id, None
        revision = self._next()
        self.offer(
            ActivityNotice(
                event_id, OutputScope(context_id, turn_id), "turn_committed", "committed", revision
            )
        )

    def signal(self, event_id: str, signal: OutputExecutionSignal) -> None:
        scope, kind = signal.scope, signal.kind
        if kind == ExecutionSignalKind.READY:
            self.offer(ActivityNotice(event_id, scope, "ready", signal.state, self._next()))
            return
        if scope.run_id is None or scope.turn_id is None:
            return

        state = self._runs.get(scope.run_id)
        if kind == ExecutionSignalKind.ACCEPTED:
            if state is not None:
                return

            state = RunActivity(scope)
            self._runs[scope.run_id] = state
            while len(self._runs) > self._max_runs:
                self._runs.popitem(last=False)
            if self.current_turn is None or self.current_turn == scope.turn_id:
                self.current_turn, self.current_run = scope.turn_id, scope.run_id
        elif state is None:
            # A journal gap is not permission to attribute an unknown run to the current user.
            return
        if state.scope != scope or state.finished:
            return

        state.revision = self._next()
        action, narration = kind.value, None
        if kind in {ExecutionSignalKind.MODEL_STARTED, ExecutionSignalKind.FINALIZING}:
            if signal.request_id != state.request_id:
                state.visible = False
                state.request_id = signal.request_id
            action = "finalizing" if kind == ExecutionSignalKind.FINALIZING else "thinking"
            narration = action if not state.visible else None
        elif kind == ExecutionSignalKind.TOOL_STARTED:
            action = "tool_start"
            narration = None if signal.commentary_output_ids else "tool_start"
        elif kind == ExecutionSignalKind.TOOL_FINISHED:
            action = "tool_success" if signal.outcome == "succeeded" else "tool_error"
            if signal.outcome == "unknown":
                narration = "tool_unknown"
            elif signal.outcome in {"failed", "denied"}:
                narration = "tool_error"
        elif kind == ExecutionSignalKind.FINISHED:
            state.finished = True
            action = "failed" if signal.state == "failed" else "idle"
            if signal.state == "failed" and not state.visible:
                narration = "failed"

        self.offer(
            ActivityNotice(
                event_id,
                scope,
                action,
                signal.state,
                state.revision,
                signal.tool_name,
                signal.outcome,
                narration,
            )
        )

    def text(self, *, run_id: str, request_id: str | None, event_id: str) -> None:
        state = self._runs.get(run_id)
        if state is None or state.finished or run_id != self.current_run:
            return
        if request_id is not None and request_id != state.request_id:
            return
        if state.visible:
            return

        state.visible = True
        state.revision = self._next()
        self.offer(
            ActivityNotice(
                event_id,
                state.scope,
                "responding",
                "responding",
                state.revision,
            )
        )

    def interrupt(self, *, run_id: str | None, turn_id: str | None, event_id: str) -> None:
        if run_id is not None and run_id != self.current_run:
            return
        if turn_id is not None and turn_id != self.current_turn:
            return
        state = self._runs.get(self.current_run or "")
        if state is None:
            return

        state.revision = self._next()
        self.offer(
            ActivityNotice(event_id, state.scope, "interrupted", "interrupted", state.revision)
        )
        self.current_run = None
