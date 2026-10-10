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
from dataclasses import dataclass, replace

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
    terminal: bool = False


@dataclass(slots=True)
class RunActivity:
    scope: OutputScope
    revision: int = 0
    request_id: str | None = None
    visible: bool = False
    finished: bool = False
    interrupted: bool = False
    notice: ActivityNotice | None = None


class StatusState:
    """Observed activity and its latest presentation, not model execution ownership."""

    def __init__(self, *, max_pending: int, max_runs: int) -> None:
        self.pending: asyncio.Queue[ActivityNotice] = asyncio.Queue(maxsize=max_pending)
        self.changed = asyncio.Event()
        self._runs: OrderedDict[str, RunActivity] = OrderedDict()
        self._max_runs = max_runs
        self._revision = 0
        self._view: ActivityNotice | None = None
        self.current_run: str | None = None
        self.current_turn: str | None = None
        self._turn_time = -1
        self.dropped = 0

    @property
    def presentation(self) -> tuple[OutputScope | None, int]:
        return (self._view.scope, self._view.revision) if self._view else (None, self._revision)

    def _next(self) -> int:
        self._revision += 1
        self.changed.set()
        return self._revision

    def current(self, scope: OutputScope, revision: int) -> bool:
        return self._view is not None and (scope, revision) == self.presentation

    def invalidate(self) -> None:
        self._view = None
        self.current_run = None
        self._next()

    def offer(self, notice: ActivityNotice, *, present: bool = False) -> None:
        if present:
            self._view = notice

        if self.pending.full():
            self.pending.get_nowait()
            self.dropped += 1

        self.pending.put_nowait(notice)

    def turn(self, *, turn_id: str, context_id: str, at_ns: int, event_id: str) -> None:
        if at_ns < self._turn_time:
            return
        self._turn_time = at_ns
        if turn_id == self.current_turn:
            return
        self.current_turn, self.current_run = turn_id, None
        self.offer(
            ActivityNotice(
                event_id,
                OutputScope(context_id, turn_id),
                "turn_committed",
                "committed",
                self._next(),
            ),
            present=True,
        )

    def signal(self, event_id: str, signal: OutputExecutionSignal) -> None:
        scope, kind = signal.scope, signal.kind
        if kind == ExecutionSignalKind.READY:
            self.offer(
                ActivityNotice(event_id, scope, "ready", signal.state, self._next()),
                present=self.current_turn is None,
            )
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
            return  # A gap never authorizes attribution to a different/current Run.
        if state.scope != scope or state.finished:
            return
        if state.interrupted and kind != ExecutionSignalKind.FINISHED:
            return

        present = self.current_run == scope.run_id or (
            self._view is not None and self._view.scope == scope
        )
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
            if state.interrupted or signal.state == "cancelled":
                action = "interrupted"
            else:
                action = "failed" if signal.state == "failed" else "idle"
                if signal.state == "failed" and not state.visible:
                    narration = "failed"
            if self.current_run == scope.run_id:
                self.current_run = None

        state.notice = ActivityNotice(
            event_id,
            scope,
            action,
            signal.state,
            state.revision,
            signal.tool_name,
            signal.outcome,
            narration,
            terminal=state.finished,
        )
        self.offer(state.notice, present=present)

    def text(self, *, run_id: str, request_id: str | None, event_id: str) -> None:
        state = self._runs.get(run_id)
        if state is None or state.interrupted or self._view is None:
            return
        if self._view.scope != state.scope:
            return
        if request_id is not None and request_id != state.request_id:
            return
        if state.visible:
            return

        state.visible = True
        state.revision = self._next()
        if state.finished:
            # Delivery observations can lag FINISHED; suppress filler, never reopen the Run.
            if state.notice is None:
                return
            notice = replace(
                state.notice, source_event_id=event_id, revision=state.revision, narration_key=None
            )
        else:
            notice = ActivityNotice(
                event_id, state.scope, "responding", "responding", state.revision
            )
        state.notice = notice
        self.offer(notice, present=True)

    def interrupt(
        self,
        *,
        run_id: str | None,
        turn_id: str | None,
        event_id: str,
        at_ns: int | None = None,
    ) -> None:
        view = self._view
        if view is None or (at_ns is not None and at_ns < self._turn_time):
            return
        if run_id is not None and run_id != view.scope.run_id:
            return
        if turn_id is not None and turn_id != view.scope.turn_id:
            return
        state = self._runs.get(view.scope.run_id or "")
        if state is None or state.interrupted:
            return

        state.interrupted = True
        state.revision = self._next()
        state.notice = ActivityNotice(
            event_id, state.scope, "interrupted", "interrupted", state.revision, terminal=True
        )
        self.current_run = None

        # Cancellation ends production, not the right to present its terminal observation.
        self.offer(state.notice, present=True)
