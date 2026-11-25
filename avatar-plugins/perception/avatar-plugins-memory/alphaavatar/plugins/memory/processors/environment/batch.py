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

from dataclasses import dataclass, field, replace

from alphaavatar.core.env import EnvObservation
from alphaavatar.core.media import MediaPayload
from alphaavatar.core.perception import (
    AlignedPerception,
    PerceptionTemporalAligner,
    TemporalAlignmentMode,
)
from alphaavatar.core.perception.schemas import PerceptionCutoff, PerceptionEvent
from alphaavatar.core.perception.source_registry import MediaSourceRegistry
from alphaavatar.core.time import RuntimeTimeRange

from .config import EnvironmentSchedulerConfig
from .input_builder import EnvMemoryInput, EnvMemoryInputBuilder


class EnvironmentBatchError(ValueError):
    pass


@dataclass(slots=True)
class EnvMemoryBatch:
    context_id: str
    from_sequence: int
    to_sequence: int
    events: tuple[PerceptionEvent, ...]
    alignment: AlignedPerception
    memory_input: EnvMemoryInput
    chat_context: str | None
    triggers: set[str] = field(default_factory=set)
    raw_event_count: int = 0
    message_count: int = 0
    payload_bytes: int = 0
    attempts: int = 0
    committed: bool = False

    @property
    def observations(self) -> list[EnvObservation]:
        return list(self.memory_input.observations)

    @property
    def conversation_context(self) -> str | None:
        return self.chat_context

    @property
    def trigger_text(self) -> str:
        return ",".join(sorted(self.triggers))

    @property
    def missed_count(self) -> int:
        return self.alignment.missed_event_count

    @property
    def raw_observation_count(self) -> int:
        return sum(event.observation is not None for event in self.events)

    def build_evidence(self) -> list[dict]:
        return list(self.memory_input.evidence)


class EnvMemoryBatchBuilder:
    def __init__(
        self,
        *,
        config: EnvironmentSchedulerConfig,
        aligner: PerceptionTemporalAligner,
        input_builder: EnvMemoryInputBuilder,
    ) -> None:
        self._config, self._aligner, self._input_builder = config, aligner, input_builder

    @staticmethod
    def _payload_bytes(payload: MediaPayload | None) -> int:
        if payload is None:
            return 0
        total, seen = 0, set()
        for view, fmt in payload.available_representations():
            value = payload.get(fmt, view=view, fallback_to_raw=False)
            value = getattr(value, "data", value)
            if id(value) in seen:
                continue
            seen.add(id(value))
            if isinstance(value, bytes | bytearray | memoryview):
                total += memoryview(value).nbytes
            elif isinstance(value, str):
                total += len(value.encode("utf-8"))
        return total

    def build(
        self,
        *,
        context_id: str,
        events: tuple[PerceptionEvent, ...],
        start_cutoff: PerceptionCutoff,
        target_cutoff: PerceptionCutoff,
        triggers: set[str],
        chat_context: str | None,
        message_count: int,
    ) -> tuple[EnvMemoryBatch, PerceptionCutoff]:
        # Select once, before retaining payloads or applying budgets. Re-sampling after
        # a clipped window would shift the visual buckets and drop selected frames.
        selected = self._input_builder.select_observations(
            (event.observation for event in events if event.observation is not None),
            origin_ns=start_cutoff.captured_at.monotonic_ns,
        )
        retained: list[PerceptionEvent] = []
        payload_bytes, consumed = 0, 0
        media_start = media_end = None
        for event in events:
            if consumed >= self._config.max_batch_events:
                break
            observation = event.observation
            keep = event.source_state is not None or (
                observation is not None and observation.observation_id in selected
            )
            captured, size = event, 0
            start, end = media_start, media_end
            if keep:
                if observation is not None:
                    payload = observation.payload.snapshot() if observation.payload else None
                    size = self._payload_bytes(payload)
                    captured = replace(
                        event,
                        payload=replace(
                            observation,
                            payload=payload,
                            metadata=dict(observation.metadata),
                            annotations=list(observation.annotations),
                        ),
                    )
                start = (
                    event.time_range.start
                    if start is None
                    else min(start, event.time_range.start, key=lambda value: value.monotonic_ns)
                )
                end = (
                    event.time_range.end
                    if end is None
                    else max(end, event.time_range.end, key=lambda value: value.monotonic_ns)
                )
                exceeds = (
                    payload_bytes + size > self._config.max_batch_payload_bytes
                    or end.elapsed_since(start) > self._config.max_batch_duration_sec
                )
                if exceeds:
                    if not retained:
                        raise EnvironmentBatchError("event_exceeds_budget")
                    break
                retained.append(captured)
                payload_bytes += size
                media_start, media_end = start, end
            consumed += 1
        if consumed == 0:
            raise EnvironmentBatchError("empty_capture")
        raw = events[:consumed]
        if consumed == len(events):
            cutoff = target_cutoff
        else:
            cutoff = PerceptionCutoff(
                sequence=raw[-1].sequence,
                captured_at=max(
                    start_cutoff.captured_at,
                    *(event.time_range.end for event in raw),
                    key=lambda value: value.monotonic_ns,
                ),
                sources=MediaSourceRegistry.project_snapshot(
                    initial_sources=start_cutoff.sources, events=raw
                ),
            )
        start = media_start or start_cutoff.captured_at
        end = media_end or max(start, cutoff.captured_at, key=lambda value: value.monotonic_ns)
        alignment = self._aligner.align(
            events=retained,
            time_range=RuntimeTimeRange(start=start, end=end),
            source_states_at_start=start_cutoff.sources,
            source_states_at_end=cutoff.sources,
            mode=TemporalAlignmentMode.FIXED,
        )
        memory_input = self._input_builder.build(alignment, selected_ids=selected)
        return EnvMemoryBatch(
            context_id=context_id,
            from_sequence=start_cutoff.sequence,
            to_sequence=cutoff.sequence,
            events=tuple(retained),
            alignment=alignment,
            memory_input=memory_input,
            chat_context=chat_context,
            triggers=set(triggers),
            raw_event_count=consumed,
            message_count=message_count,
            payload_bytes=payload_bytes,
        ), cutoff
