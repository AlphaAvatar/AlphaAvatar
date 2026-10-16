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
import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.host.processes.process import ExecutionProcess
from alphaavatar.host.processes.schemas import ProcessResult
from alphaavatar.host.processes.supervisor import ProcessSupervisor
from alphaavatar.host.sessions.schemas import SessionRequest

from .policy import ExecutionPolicy
from .schemas import TERMINAL_STATES, ExecutionReservation, ExecutionState, ExecutionView


@dataclass(slots=True)
class _Execution:
    reservation: ExecutionReservation
    done: asyncio.Future[ProcessResult]

    state: ExecutionState = "reserved"
    reason: str = ""
    process: ExecutionProcess | None = None
    pid: int | None = None
    task: asyncio.Task[None] | None = None


class ExecutionManager:
    """Own admission leases and remote execution handles, never a child's Engine object."""

    def __init__(
        self,
        supervisor: ProcessSupervisor,
        *,
        capacity: int,
        policy: ExecutionPolicy,
        admission_ready: Callable[[], bool] = lambda: True,
    ) -> None:
        self._supervisor, self._capacity, self._policy = supervisor, capacity, policy
        self._admission_ready = admission_ready

        self._records: dict[tuple[str, str], _Execution] = {}
        self._draining = False
        self._close_task: asyncio.Task[None] | None = None
        self._failure: Exception | None = None
        self.changed = asyncio.Event()

    @property
    def healthy(self) -> bool:
        return self._failure is None

    @property
    def active_count(self) -> int:
        self._expire()
        return sum(record.state not in TERMINAL_STATES for record in self._records.values())

    @property
    def available(self) -> bool:
        return (
            not self._draining
            and self.healthy
            and self._admission_ready()
            and self.active_count < self._capacity
            and len(self._records) < self._policy.ledger_capacity
        )

    @property
    def load(self) -> float:
        return min(self.active_count / self._capacity, 1.0) if self.available else 1.0

    def _set_state(self, record: _Execution, state: ExecutionState, reason: str = "") -> None:
        record.state, record.reason = state, reason
        self.changed.set()

    def _cancel_reservation(self, record: _Execution, reason: str) -> None:
        self._set_state(record, "cancelled", reason)
        if not record.done.done():
            record.done.set_result(
                ProcessResult(
                    execution_id=record.reservation.execution_id,
                    outcome="failed",
                    reason=reason,
                )
            )

    def _expire(self) -> None:
        now = time.monotonic()
        for record in self._records.values():
            if record.state == "reserved" and record.reservation.expires_at <= now:
                self._cancel_reservation(record, "reservation_expired")

    def reserve(self, *, backend: str, source_id: str) -> ExecutionReservation | None:
        if not backend or not source_id or len(source_id) > 256:
            return None

        key = (backend, source_id)
        if key in self._records or not self.available:
            return None

        reservation = ExecutionReservation(
            execution_id=uuid4().hex,
            attachment_id=uuid4().hex,
            backend=backend,
            source_id=source_id,
            lease_id=uuid4().hex,
            expires_at=time.monotonic() + self._policy.reservation_timeout,
        )
        self._records[key] = _Execution(reservation, asyncio.get_running_loop().create_future())
        self.changed.set()
        return reservation

    def cancel_reservation(self, reservation: ExecutionReservation, reason: str) -> None:
        record = self._records.get((reservation.backend, reservation.source_id))
        if record is not None and record.reservation == reservation and record.state == "reserved":
            self._cancel_reservation(record, reason)

    def reservation_valid(self, reservation: ExecutionReservation) -> bool:
        self._expire()
        record = self._records.get((reservation.backend, reservation.source_id))
        return bool(
            not self._draining
            and self.healthy
            and self._admission_ready()
            and record is not None
            and record.reservation == reservation
            and record.state == "reserved"
        )

    def assign(self, reservation: ExecutionReservation, request: SessionRequest) -> bool:
        self._expire()
        record = self._records.get((reservation.backend, reservation.source_id))
        if (
            self._draining
            or not self.healthy
            or not self._admission_ready()
            or record is None
            or record.reservation != reservation
            or record.state != "reserved"
            or request.backend != reservation.backend
            or request.source_id != reservation.source_id
            or request.attachment_id != reservation.attachment_id
        ):
            return False

        try:
            record.process = self._supervisor.create(reservation.execution_id, request)
        except Exception:
            self._cancel_reservation(record, "process_admission_failed")
            return False

        self._set_state(record, "starting")
        record.task = asyncio.create_task(
            self._launch(record), name=f"host_execution:{reservation.execution_id}"
        )
        record.task.add_done_callback(lambda task: None if task.cancelled() else task.exception())
        return True

    async def _launch(self, record: _Execution) -> None:
        process = record.process
        assert process is not None
        result: ProcessResult | None = None
        try:
            try:
                await process.on_start()
                record.pid = process.pid
                if record.state != "stopping":
                    self._set_state(record, "running")

                result = await process.wait()
            except (asyncio.CancelledError, Exception):
                await process.on_stop()
                result = await process.wait()
        except (asyncio.CancelledError, Exception) as error:
            self._failure = RuntimeError("Execution process could not be settled")
            self._failure.__cause__ = error
        finally:
            try:
                await self._supervisor.release(process)
            except (asyncio.CancelledError, Exception) as error:
                self._failure = RuntimeError("Execution process could not be reaped")
                self._failure.__cause__ = error
                result = None
            if result is None:
                result = ProcessResult(
                    execution_id=record.reservation.execution_id,
                    outcome="unknown",
                    reason="execution_outcome_unknown",
                )
            record.pid = process.pid
            if process.reaped:
                record.process = None
            self._set_state(record, result.outcome, result.reason)
            if not record.done.done():
                record.done.set_result(result)

    def request_stop(self, *, backend: str, source_id: str, reason: str) -> None:
        record = self._records.get((backend, source_id))
        if record is None or record.state in TERMINAL_STATES:
            return
        if record.state == "reserved":
            self._cancel_reservation(record, reason)
            return
        self._set_state(record, "stopping", reason)
        assert record.process is not None
        record.process.request_stop(reason)

    async def wait(self, reservation: ExecutionReservation) -> ProcessResult:
        record = self._records[(reservation.backend, reservation.source_id)]
        if record.reservation != reservation:
            raise ValueError("Execution reservation changed")
        return await asyncio.shield(record.done)

    def snapshot(self) -> tuple[ExecutionView, ...]:
        self._expire()
        return tuple(
            ExecutionView(
                execution_id=record.reservation.execution_id,
                backend=record.reservation.backend,
                source_id=record.reservation.source_id,
                state=record.state,
                reason=record.reason,
                pid=record.process.pid if record.process is not None else record.pid,
            )
            for record in self._records.values()
        )

    def stop_accepting(self) -> None:
        self._draining = True
        for record in self._records.values():
            if record.state == "reserved":
                self._cancel_reservation(record, "host_draining")
        self.changed.set()

    async def _close(self) -> None:
        self.stop_accepting()
        for backend, source_id in self._records:
            self.request_stop(backend=backend, source_id=source_id, reason="host_shutdown")
        tasks = tuple(record.task for record in self._records.values() if record.task is not None)
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._failure is not None:
            raise self._failure

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="execution_manager_close")
            self._close_task.add_done_callback(
                lambda task: None if task.cancelled() else task.exception()
            )
        await wait_for_cleanup(self._close_task)
