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
from collections import OrderedDict
from typing import TYPE_CHECKING, Protocol

from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.output.enums import OutputLane
from alphaavatar.core.output.enums.message_phase import OutputMessagePhase
from alphaavatar.core.output.schemas import OutputIdentity

from .segmentation import SegmentPreparer
from .state import PreparedSpeech, SpeechJob, SpeechLimits

if TYPE_CHECKING:
    from alphaavatar.core.output.runtime import OutputRuntime

logger = logging.getLogger(__name__)


class CancelSpeech(Protocol):
    def __call__(self, job: SpeechJob, *, reason: str | None = None) -> None: ...


class AnswerHandoff:
    """Prepare one answer and retire only its same-scope commentary outputs."""

    def __init__(
        self,
        *,
        output: OutputRuntime,
        jobs: OrderedDict[str, SpeechJob],
        segments: SegmentPreparer,
        wake: asyncio.Event,
        cancel: CancelSpeech,
        capacity: int,
        limits: SpeechLimits,
    ) -> None:
        self._output, self._jobs, self._segments = output, jobs, segments
        self._wake, self._cancel, self._capacity = wake, cancel, capacity
        self._limits = limits
        self._slot = asyncio.Lock()
        self._commentaries: dict[str, OutputIdentity] = {}

    def clear(self) -> None:
        self._commentaries.clear()

    def targets(self, job: SpeechJob) -> tuple[OutputIdentity, ...]:
        output = self._output
        for output_id, identity in tuple(self._commentaries.items()):
            if output.output_identity(output_id) != identity or not output.can_deliver(output_id):
                self._commentaries.pop(output_id, None)

        return tuple(
            identity
            for identity in self._commentaries.values()
            if identity.scope == job.identity.scope and identity.output_id != job.identity.output_id
        )

    def plan(self, job: SpeechJob) -> None:
        if job.identity.lane != OutputLane.ASSISTANT or job.cancelled:
            return

        targets = self.targets(job)
        if job.phase == OutputMessagePhase.COMMENTARY:
            if (
                job.identity.output_id not in self._commentaries
                and len(self._commentaries) >= self._limits.max_outputs
            ):
                raise RuntimeError("Commentary delivery capacity exhausted")
            self._commentaries[job.identity.output_id] = job.identity
            return
        if job.phase != OutputMessagePhase.FINAL_ANSWER or not targets or job.handoff is not None:
            return
        if job.running and not job.audio_attempted:
            return  # Its normal first-frame path will perform the switch.
        if not job.running and not job.peek(4096).strip():
            return

        operation = self.supersede(job) if job.audio_attempted else self._prepare_answer(job)
        job.handoff = asyncio.create_task(operation, name="speech_answer_handoff")

        # Observe now, but propagate the result through this job's owned settlement.
        job.handoff.add_done_callback(self._observe_preparation)

    @staticmethod
    def _observe_preparation(task: asyncio.Task) -> None:
        if not task.cancelled():
            task.exception()

    async def supersede(self, job: SpeechJob, *, unstarted: bool = False) -> None:
        output = self._output
        for identity in self.targets(job):
            if job.cancelled or not output.can_deliver(job.identity.output_id):
                return

            previous = self._jobs.get(identity.output_id)
            if unstarted and (previous is None or previous.audio_attempted):
                continue

            if previous is not None:
                self._cancel(previous, reason="commentary_superseded")

            # Never revoke the Run: its final answer and real tool results are still valid.
            async with asyncio.timeout(self._limits.timeout):
                await output.interrupt(
                    output_id=identity.output_id,
                    turn_id=identity.scope.turn_id,
                    reason="commentary_superseded",
                )
            self._commentaries.pop(identity.output_id, None)
            logger.debug(
                "Speech commentary superseded output_id=%s by_output_id=%s",
                identity.output_id,
                job.identity.output_id,
            )

    def _release_slot(self, job: SpeechJob) -> None:
        if job.owns_handoff_slot:
            job.owns_handoff_slot = False
            self._slot.release()

    async def _prepare_answer(self, job: SpeechJob) -> None:
        await self._slot.acquire()
        job.owns_handoff_slot = True
        try:
            if job.cancelled or not self._output.can_deliver(job.identity.output_id):
                raise asyncio.CancelledError
            if self._capacity < 3:
                # With no extra preparation slot, stop only the old commentary and await
                # its owned stream reclamation before requesting the answer's first frame.
                tasks = tuple(
                    previous.task
                    for identity in self.targets(job)
                    if (previous := self._jobs.get(identity.output_id)) is not None
                    and previous.task is not None
                )
                await self.supersede(job)
                async with asyncio.timeout(self._limits.timeout):
                    results = await asyncio.gather(
                        *(asyncio.shield(task) for task in tasks), return_exceptions=True
                    )
                for result in results:
                    if isinstance(result, Exception):
                        raise result
            else:
                await self.supersede(job, unstarted=True)
            try:
                prepared = await self._segments.prepare(job)
            except Exception as error:
                # A failed future answer is an output failure, not a consumer shutdown failure.
                job.preparation_error = error
                logger.warning(
                    "Answer preparation failed output_id=%s error_type=%s",
                    job.identity.output_id,
                    type(error).__name__,
                )
                self._release_slot(job)
                prepared = None
            # Transfer stream ownership before suspension, including during interruption.
            job.prefetched = prepared
            if prepared is not None and prepared.first is not None:
                await self.supersede(job)
            if not job.cancelled and self._jobs.get(job.identity.output_id) is job:
                self._jobs.move_to_end(job.identity.output_id, last=False)
            self._wake.set()
        except BaseException:
            prepared, job.prefetched = job.prefetched, None
            try:
                if prepared is not None:
                    await wait_for_cleanup(asyncio.create_task(prepared.aclose()))
            finally:
                self._release_slot(job)
            raise

    async def first_segment(self, job: SpeechJob) -> PreparedSpeech | None:
        if job.handoff is None:
            return await self._segments.prepare(job)
        await asyncio.shield(job.handoff)
        job.handoff = None
        if job.preparation_error is not None:
            raise job.preparation_error
        prepared, job.prefetched = job.prefetched, None
        self._release_slot(job)
        return prepared

    async def reap(self, job: SpeechJob, *, cancel: bool = True) -> None:
        task, job.handoff = job.handoff, None
        error = None
        if task is not None:
            if cancel and not task.done():
                task.cancel()
            (result,) = await asyncio.gather(task, return_exceptions=True)
            if isinstance(result, Exception):
                error = result
        prepared, job.prefetched = job.prefetched, None
        try:
            if prepared is not None:
                await prepared.aclose()
        finally:
            self._release_slot(job)
            if error is not None:
                raise error
