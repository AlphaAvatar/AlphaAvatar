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
from dataclasses import dataclass

from alphaavatar.agents.avatar.voice import VADBase
from alphaavatar.agents.router import RouterProcessorBase
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.env.enums import ObservationKind, SpeechCancellationReason
from alphaavatar.core.env.schemas import PerceptionSourceRef
from alphaavatar.core.media import AudioFrame, PayloadFormatUnavailable
from alphaavatar.core.media.enums import PayloadFormat, PayloadView
from alphaavatar.core.perception.enums import MediaModality, MediaSourceState
from alphaavatar.core.perception.schemas import PerceptionEvent

from .config import AudioActivityConfig
from .source import AudioActivitySource

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _InputState:
    generation: int
    state: MediaSourceState = MediaSourceState.ACTIVE
    changed_sequence: int = 0


class AudioActivityProcessor(RouterProcessorBase):
    CONSUMER_ID = "router.audio_activity"

    def __init__(
        self, *, runtime: AvatarRuntime, vad: VADBase, config: AudioActivityConfig
    ) -> None:
        super().__init__(runtime=runtime)

        self._vad = vad
        self._config = config

        self._sources: dict[PerceptionSourceRef, AudioActivitySource] = {}
        self._closing_sources: dict[PerceptionSourceRef, AudioActivitySource] = {}

        # Keep the latest lifecycle of each admitted input; old generations cannot reopen it.
        self._inputs: dict[str, _InputState] = {}
        self._last_sequence = 0
        self._task: asyncio.Task[None] | None = None
        self._started = False

    @property
    def name(self) -> str:
        return "audio_activity"

    @staticmethod
    def _extract_frame(observation: EnvObservation) -> AudioFrame | None:
        if observation.payload is None:
            return None

        try:
            frame = observation.payload.get(
                PayloadFormat.AUDIO_FRAME, view=PayloadView.RAW, fallback_to_raw=False
            )
        except PayloadFormatUnavailable:
            return None

        return frame if isinstance(frame, AudioFrame) else None

    def _record(
        self, stage: str, source: PerceptionSourceRef, *, sequence: int, reason: str
    ) -> None:
        self._runtime.perception.input_trace.record(
            stage,
            input_source_id=source.source_id,
            input_source_generation=source.source_generation,
            sequence=sequence,
            reason=reason,
        )

    def _create_source(
        self, observation: EnvObservation, frame: AudioFrame
    ) -> AudioActivitySource | None:
        if len(self._sources) + len(self._closing_sources) >= self._config.max_sources:
            self._record(
                "audio.input_rejected",
                observation.source,
                sequence=self._last_sequence,
                reason="source_cleanup_capacity",
            )
            return None
        source = AudioActivitySource(
            perception_runtime=self._runtime.perception,
            input_source=observation.source,
            vad=self._vad,
            sample_rate=frame.sample_rate,
            num_channels=frame.num_channels,
            pre_roll_sec=self._config.pre_roll_sec,
            max_buffer_sec=self._config.max_buffer_sec,
            close_timeout_sec=self._config.close_timeout_sec,
            on_failed=self._source_failed,
        )
        self._sources[observation.source] = source
        return source

    def _source_failed(self, source: AudioActivitySource, reason: SpeechCancellationReason) -> None:
        self._retire_source(source, reason=reason)

    def _observe_cleanup(self, source: AudioActivitySource) -> None:
        pending = [task for task in source.cleanup_tasks if not task.done()]
        for task in source.cleanup_tasks:
            if task.done() and not task.cancelled():
                task.exception()
        if not pending:
            self._closing_sources.pop(source.speech_source, None)
            return
        # A provider that ignores cancellation keeps its slot until it really exits.
        for task in pending:
            task.add_done_callback(lambda _task: self._observe_cleanup(source))

    def _retire_source(
        self,
        source: AudioActivitySource,
        *,
        reason: SpeechCancellationReason,
        graceful: bool = False,
    ) -> asyncio.Task[None]:
        if self._sources.get(source.input_source) is source:
            self._sources.pop(source.input_source)
        existing = source.speech_source in self._closing_sources
        self._closing_sources[source.speech_source] = source
        task = source.begin_close(graceful=graceful, reason=reason)
        if not existing:
            task.add_done_callback(lambda _task: self._observe_cleanup(source))
        return task

    def _accept_input(self, source: PerceptionSourceRef) -> _InputState | None:
        current = self._inputs.get(source.source_id)
        if current is not None and source.source_generation < current.generation:
            return None
        if current is None and len(self._inputs) >= self._config.max_sources:
            self._record(
                "audio.input_rejected",
                source,
                sequence=self._last_sequence,
                reason="source_capacity",
            )
            return None
        if current is None or source.source_generation > current.generation:
            for previous in tuple(self._sources.values()):
                if previous.input_source.source_id == source.source_id:
                    self._retire_source(
                        previous, reason=SpeechCancellationReason.SOURCE_GENERATION_RETIRED
                    )
            current = self._inputs[source.source_id] = _InputState(source.source_generation)
        return current

    def _consume_source_state(
        self, source: PerceptionSourceRef, state: MediaSourceState, sequence: int
    ) -> None:
        current = self._accept_input(source)
        if current is None or sequence < current.changed_sequence or current.state.terminal:
            return
        current.state, current.changed_sequence = state, sequence
        if state.available:
            return
        reason = {
            MediaSourceState.MUTED: SpeechCancellationReason.SOURCE_MUTED,
            MediaSourceState.ENDED: SpeechCancellationReason.SOURCE_ENDED,
            MediaSourceState.ERROR: SpeechCancellationReason.SOURCE_ERROR,
        }[state]
        self._record("audio.source_invalidated", source, sequence=sequence, reason=reason.value)
        active = self._sources.get(source)
        if active is not None:
            self._retire_source(active, reason=reason)

    def _consume_observation(self, observation: EnvObservation, sequence: int) -> None:
        current = self._accept_input(observation.source)
        if current is None or not current.state.available or sequence < current.changed_sequence:
            return
        frame = self._extract_frame(observation)
        if frame is None:
            active = self._sources.get(observation.source)
            if active is not None:
                self._retire_source(active, reason=SpeechCancellationReason.PROCESSING_ERROR)
            return
        source = self._sources.get(observation.source)
        if source is not None and (source.failed or not source.matches(frame)):
            self._retire_source(source, reason=SpeechCancellationReason.SOURCE_REPLACED)
            source = None
        source = source if source is not None else self._create_source(observation, frame)
        if source is None or source.push(observation, frame):
            return
        self._retire_source(source, reason=SpeechCancellationReason.VAD_INPUT_REJECTED)
        replacement = self._create_source(observation, frame)
        if replacement is not None and not replacement.push(observation, frame):
            self._retire_source(replacement, reason=SpeechCancellationReason.VAD_INPUT_REJECTED)

    def _consume_event(self, event: PerceptionEvent) -> None:
        self._last_sequence = event.sequence
        state = event.source_state
        if state is not None and state.modality == MediaModality.AUDIO:
            self._consume_source_state(state.source, state.state, event.sequence)
        observation = event.observation
        if observation is not None and observation.kind == ObservationKind.AUDIO_FRAME:
            self._consume_observation(observation, event.sequence)

    def _recover_gap(self, missed_count: int, cursor_sequence: int) -> None:
        trace = self._runtime.perception.input_trace
        trace.record("audio.input_gap", missed_count=missed_count, sequence=cursor_sequence)
        trace.freeze("audio_input_gap")
        for source in tuple(self._sources.values()):
            self._retire_source(source, reason=SpeechCancellationReason.INPUT_GAP)
        # The snapshot can be newer than the retained batch. Its sequence also rejects
        # frames from before an unmute/reconnect boundary whose event was overwritten.
        for state in self._runtime.perception.get_source_states(modality=MediaModality.AUDIO):
            self._consume_source_state(state.source, state.state, state.changed_sequence)

    async def _consume_loop(self) -> None:
        stream = self._runtime.perception.events
        while True:
            try:
                await stream.wait_for_pending(consumer_id=self.CONSUMER_ID)
                batch = stream.read_pending(
                    consumer_id=self.CONSUMER_ID, limit=self._config.event_batch_size
                )
                if batch.has_gap:
                    self._recover_gap(batch.missed_count, batch.cursor_seq)
                for event in batch.items:
                    try:
                        self._consume_event(event)
                    except Exception:
                        observation = event.observation
                        source = self._sources.get(observation.source) if observation else None
                        if source is not None:
                            self._retire_source(
                                source, reason=SpeechCancellationReason.PROCESSING_ERROR
                            )
                        logger.exception("Audio Activity failed event_sequence=%s", event.sequence)
                stream.commit(consumer_id=self.CONSUMER_ID, cursor_seq=batch.cursor_seq)
                self._last_sequence = batch.cursor_seq
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Audio Activity failed to consume events")
                await asyncio.sleep(0.05)

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        if self._last_sequence:
            self._runtime.perception.events.commit(
                consumer_id=self.CONSUMER_ID, cursor_seq=self._last_sequence
            )
        self._task = asyncio.create_task(self._consume_loop(), name="router_audio_activity")

    async def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        for source in tuple(self._sources.values()):
            self._retire_source(source, graceful=True, reason=SpeechCancellationReason.SHUTDOWN)
        tasks = {
            task
            for source in self._closing_sources.values()
            for task in source.cleanup_tasks
            if not task.done()
        }
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=self._config.close_timeout_sec)
            for task in pending:
                task.cancel()
            await asyncio.sleep(0)
        self._runtime.perception.events.clear_consumer(self.CONSUMER_ID)
