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
from collections import deque
from contextlib import suppress

from .process import RunnerProcess


class RunnerPool:
    """Schedule one method over independent runner processes that each run one request.

    Waiting requests stay here in arrival order and go to whichever worker frees first;
    none is queued inside a worker. ``max_pending`` counts every admitted request that has
    not settled: waiting, handed over, or executing, including a dispatched request whose
    caller left, since its worker still owns the response.
    """

    def __init__(self, method: str, workers: int, *, max_pending: int) -> None:
        self.method = method
        self.slots: list[RunnerProcess | None] = [None] * workers
        self._max_pending = max_pending
        self._waiters: deque[asyncio.Future[RunnerProcess]] = deque()
        self._reserved: set[RunnerProcess] = set()
        self.rejected = self.queue_timeouts = self.execution_timeouts = self.restarts = 0

    @property
    def ready_workers(self) -> int:
        return sum(worker is not None and worker.is_alive for worker in self.slots)

    @property
    def executing(self) -> int:
        busy = sum(worker is not None and worker.busy for worker in self.slots)
        return busy + len(self._reserved)

    @property
    def waiting(self) -> int:
        return sum(not waiter.done() for waiter in self._waiters)

    def _idle(self) -> RunnerProcess | None:
        for worker in self.slots:
            if (
                worker is not None
                and worker.is_alive
                and not worker.busy
                and worker not in self._reserved
            ):
                return worker
        return None

    def wake(self) -> None:
        """Hand idle workers to the oldest waiters; fail the rest once no worker can serve."""
        while self._waiters:
            if self._waiters[0].done():
                self._waiters.popleft()
                continue
            worker = self._idle()
            if worker is None:
                if not self.ready_workers:
                    for waiter in self._waiters:
                        if not waiter.done():
                            waiter.set_exception(
                                RuntimeError("Inference runner temporarily unavailable")
                            )
                    self._waiters.clear()
                return
            self._reserved.add(worker)
            self._waiters.popleft().set_result(worker)

    async def run(self, data: bytes, *, queue_timeout: float, timeout: float) -> bytes | None:
        if not self.ready_workers:
            raise RuntimeError("Inference runner temporarily unavailable")
        if self.executing + self.waiting >= self._max_pending:
            self.rejected += 1
            raise RuntimeError(f"Inference runner {self.method!r} is at capacity")
        worker = None if self.waiting else self._idle()
        if worker is None:
            waiter = asyncio.get_running_loop().create_future()
            self._waiters.append(waiter)
            try:
                async with asyncio.timeout(queue_timeout):
                    worker = await waiter
            except BaseException as error:
                if waiter.done() and not waiter.cancelled() and waiter.exception() is None:
                    # Handed a worker as this caller left: pass it on, nothing was dispatched.
                    self._reserved.discard(waiter.result())
                    self.wake()
                else:
                    waiter.cancel()
                    with suppress(ValueError):
                        self._waiters.remove(waiter)
                if isinstance(error, TimeoutError):
                    # Withdrawn before dispatch: it never runs, now or later.
                    self.queue_timeouts += 1
                    raise TimeoutError(
                        f"Inference request for {self.method!r} expired waiting for a worker"
                    ) from None
                raise
            self._reserved.discard(worker)
        try:
            # Registers on the worker before yielding, so no other request can take it.
            return await worker.run(data, timeout=timeout)
        except TimeoutError:
            self.execution_timeouts += 1
            raise
