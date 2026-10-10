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
from typing import TYPE_CHECKING

from alphaavatar.agents.status import StatusProcessorBase
from alphaavatar.core.output.enums import OutputKind, OutputLane, OutputTextMode
from alphaavatar.core.output.enums.audience import OutputAudience
from alphaavatar.core.output.schemas.decision import OutputStatusDecision

from ...state import StatusState
from ...tasks import spawn
from .config import NarrationConfig
from .renderer import RuleNarrator

if TYPE_CHECKING:
    from alphaavatar.agents.runtime import AvatarRuntime

logger = logging.getLogger(__name__)


class NarrationProcessor(StatusProcessorBase):
    SUBSCRIPTION = "status.narration.decisions"

    def __init__(self, runtime: AvatarRuntime, state: StatusState, config: NarrationConfig) -> None:
        self._runtime, self._state, self._config = runtime, state, config
        self._renderer = RuleNarrator(config.language)
        self._subscription = None
        self._tasks: list[asyncio.Task] = []
        self._job: asyncio.Task | None = None
        self._decision: OutputStatusDecision | None = None
        self._output_id: str | None = None
        self._lock = asyncio.Lock()

    def _valid(self, decision: OutputStatusDecision) -> bool:
        return (
            decision.audience == OutputAudience.USER
            and self._runtime.clock.now().monotonic_ns <= decision.expires_at_ns
            and self._state.current(decision.scope, decision.revision)
            and self._runtime.output.accepts_run(decision.scope.run_id)
        )

    async def _clear(self) -> None:
        task, self._job = self._job, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        output_id, self._output_id = self._output_id, None
        self._decision = None
        if output_id is not None:
            try:
                async with asyncio.timeout(self._config.publish_timeout):
                    await self._runtime.output.interrupt(
                        output_id=output_id, reason="status_superseded"
                    )
            except Exception:
                logger.exception("Status speech interruption failed")

    async def _speak(self, decision: OutputStatusDecision) -> None:
        try:
            async with asyncio.timeout(self._config.publish_timeout):
                text = await self._renderer.render(decision.narration_key)
                if not text or not self._valid(decision):
                    return

                interaction = self._runtime.state.interaction_method
                if not interaction.audio_output and not interaction.text_output:
                    return

                mode = (
                    OutputTextMode.AUDIO_SYNCED
                    if interaction.audio_output
                    else OutputTextMode.IMMEDIATE
                )
                output_id = f"status:{decision.decision_id}"
                self._output_id = output_id
                event = await self._runtime.output.publish_text_chunk(
                    text=text,
                    output_id=output_id,
                    turn_id=decision.scope.turn_id,
                    lane=OutputLane.TRANSIENT,
                    mode=mode,
                    is_final=True,
                    run_id=decision.scope.run_id,
                    metadata={
                        "origin": "status.narration",
                        "decision_id": decision.decision_id,
                        "source_event_id": decision.source_event_id,
                        "context_id": decision.scope.context_id,
                    },
                )
                if event is not None and not interaction.audio_output:
                    await self._runtime.output.complete(
                        lane=OutputLane.TRANSIENT,
                        output_id=output_id,
                        turn_id=decision.scope.turn_id,
                    )
                # AUDIO_SYNCED completion belongs to the speech-synthesis producer.
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Status narration failed")

    async def _decisions(self) -> None:
        while True:
            event = await self._subscription.get()
            decision = event.payload
            if not isinstance(decision, OutputStatusDecision) or not decision.narration_key:
                continue

            if not self._valid(decision):
                continue

            async with self._lock:
                await self._clear()
                if self._valid(decision):
                    self._decision = decision
                    self._job = spawn(self._speak(decision), name="status:narrate")

    async def _changes(self) -> None:
        while True:
            await self._state.changed.wait()
            self._state.changed.clear()
            async with self._lock:
                if self._decision is not None and not self._valid(self._decision):
                    await self._clear()

    async def start(self) -> None:
        if self._tasks or not self._config.enabled:
            return

        self._subscription = await self._runtime.output.stream.subscribe(
            self.SUBSCRIPTION,
            kinds=(OutputKind.STATUS,),
            lanes=(OutputLane.STATUS,),
            max_pending=32,
            reliable=False,
        )
        self._tasks = [
            spawn(self._decisions(), name="status:decisions"),
            spawn(self._changes(), name="status:changes"),
        ]

    async def stop(self) -> None:
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)
        await self._clear()
        if self._subscription is not None:
            await self._runtime.output.stream.unsubscribe(self.SUBSCRIPTION)
            self._subscription = None
