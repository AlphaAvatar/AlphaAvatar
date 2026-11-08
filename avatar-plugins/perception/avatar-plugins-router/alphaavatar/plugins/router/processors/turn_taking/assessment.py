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
from collections.abc import Callable, Coroutine, Iterator
from contextlib import contextmanager

from alphaavatar.agents.router.schemas import TurnTakingEvidence
from alphaavatar.agents.runtime import AvatarRuntime


class AssessmentWork:
    """Replaceable decisions, retaining every cancelled worker until it finishes."""

    def __init__(self, runtime: AvatarRuntime) -> None:
        self._runtime = runtime

        self._current: dict[str, asyncio.Task[None]] = {}
        self._workers: set[asyncio.Task[None]] = set()

    def _done(self, input_id: str, task: asyncio.Task[None]) -> None:
        self._workers.discard(task)
        if self._current.get(input_id) is task:
            self._current.pop(input_id, None)
        if not task.cancelled():
            task.exception()

    @contextmanager
    def span(self, stage: str, evidence: TurnTakingEvidence, **fields: object) -> Iterator[None]:
        started, outcome = self._runtime.clock.now().monotonic_ns, "done"
        try:
            yield
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except Exception:
            outcome = "failed"
            raise
        finally:
            self._runtime.perception.input_trace.record(
                stage,
                input_id=evidence.input_id,
                revision=evidence.revision,
                start_time_ns=started,
                end_time_ns=self._runtime.clock.now().monotonic_ns,
                outcome=outcome,
                **fields,
            )

    def cancel(self, input_id: str) -> None:
        task = self._current.pop(input_id, None)
        if (
            task is not None
            and task is not asyncio.current_task()
            and not task.done()
            and not task.cancelling()
        ):
            task.cancel()

    def start(
        self, input_id: str, operation: Callable[[], Coroutine[object, object, None]]
    ) -> None:
        self.cancel(input_id)
        task = asyncio.create_task(operation(), name=f"router_turn_assessment:{input_id}")
        self._current[input_id] = task
        self._workers.add(task)
        task.add_done_callback(lambda done: self._done(input_id, done))

    async def reset(self) -> None:
        tasks = tuple(self._workers)
        self._current.clear()
        for task in tasks:
            if not task.done() and not task.cancelling():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._workers.difference_update(tasks)
