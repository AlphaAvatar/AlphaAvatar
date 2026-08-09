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

from dataclasses import dataclass
from typing import Any

from alphaavatar.agents.constants import VIDEO_MEMORY_INTERVAL_SEC
from alphaavatar.agents.providers.schema import (
    ModelTemporalPart,
    ModelTemporalSlice,
)
from alphaavatar.core.env import EnvObservation, ObservationKind
from alphaavatar.core.perception import (
    AlignedPerception,
    MediaSourceSnapshot,
)


@dataclass(frozen=True, slots=True)
class EnvMemoryInput:
    temporal: ModelTemporalPart
    evidence: tuple[dict[str, Any], ...]
    has_environment_evidence: bool

    @property
    def alignment(self) -> AlignedPerception:
        return self.temporal.alignment

    @property
    def slices(self) -> tuple[ModelTemporalSlice, ...]:
        return self.temporal.slices

    @property
    def observations(self) -> tuple[EnvObservation, ...]:
        return self.temporal.observations


class EnvMemoryInputBuilder:
    """
    Select environment evidence without provider encoding.

    Visual frames are sampled here because that is an ENV Memory policy.
    Ambient audio remains as original AUDIO_FRAME/AUDIO_SEGMENT observations.
    Provider adapters decide how to package or encode it.
    """

    _VISUAL_KINDS = {
        ObservationKind.VIDEO_FRAME,
        ObservationKind.SCREEN_FRAME,
    }

    _AUDIO_KINDS = {
        ObservationKind.AUDIO_FRAME,
        ObservationKind.AUDIO_SEGMENT,
    }

    def __init__(
        self,
        *,
        include_audio: bool = True,
    ) -> None:
        self._video_interval_ns = round(VIDEO_MEMORY_INTERVAL_SEC * 1_000_000_000)
        self._include_audio = include_audio

    @staticmethod
    def _observation_key(observation: EnvObservation) -> tuple[int, int, str]:
        return (
            observation.time_range.start.monotonic_ns,
            observation.time_range.end.monotonic_ns,
            observation.observation_id,
        )

    @staticmethod
    def _source_key(observation: EnvObservation) -> tuple[str, int | None]:
        generation = observation.metadata.get("source_generation")
        return (
            observation.source_id,
            generation if isinstance(generation, int) else None,
        )

    @staticmethod
    def _is_direct_upload(observation: EnvObservation) -> bool:
        return observation.metadata.get("input_origin") == "direct_upload"

    def _selected_visual_ids(
        self,
        alignment: AlignedPerception,
    ) -> set[str]:
        origin_ns = alignment.time_range.start.monotonic_ns
        buckets: dict[
            tuple[str, int | None, int],
            EnvObservation,
        ] = {}

        observations = {
            observation.observation_id: observation
            for temporal_slice in alignment.slices
            for observation in temporal_slice.observations
            if observation.kind in self._VISUAL_KINDS and not self._is_direct_upload(observation)
        }

        for observation in sorted(
            observations.values(),
            key=self._observation_key,
        ):
            source_id, generation = self._source_key(observation)
            bucket = (
                max(
                    0,
                    observation.time_range.end.monotonic_ns - origin_ns,
                )
                // self._video_interval_ns
            )
            buckets[source_id, generation, bucket] = observation

        return {observation.observation_id for observation in buckets.values()}

    def _build_slices(
        self,
        alignment: AlignedPerception,
    ) -> tuple[ModelTemporalSlice, ...]:
        selected_visual_ids = self._selected_visual_ids(alignment)

        raw_audio_sources = {
            self._source_key(observation)
            for temporal_slice in alignment.slices
            for observation in temporal_slice.observations
            if observation.kind == ObservationKind.AUDIO_FRAME
            and not self._is_direct_upload(observation)
        }

        slices: list[ModelTemporalSlice] = []

        for temporal_slice in alignment.slices:
            selected: dict[str, EnvObservation] = {}

            for observation in temporal_slice.observations:
                if self._is_direct_upload(observation):
                    continue

                if observation.kind in self._VISUAL_KINDS:
                    if observation.observation_id in selected_visual_ids:
                        selected[observation.observation_id] = observation
                    continue

                if not self._include_audio or observation.kind not in self._AUDIO_KINDS:
                    continue

                # Prefer raw continuous audio frames. AUDIO_SEGMENT is only a
                # fallback when the original frames are unavailable.
                if (
                    observation.kind == ObservationKind.AUDIO_SEGMENT
                    and self._source_key(observation) in raw_audio_sources
                ):
                    continue

                selected[observation.observation_id] = observation

            if selected or temporal_slice.source_events:
                slices.append(
                    ModelTemporalSlice(
                        index=temporal_slice.index,
                        time_range=temporal_slice.time_range,
                        observations=tuple(
                            sorted(
                                selected.values(),
                                key=self._observation_key,
                            )
                        ),
                        source_events=temporal_slice.source_events,
                    )
                )

        return tuple(slices)

    @staticmethod
    def _state_map(
        states: tuple[MediaSourceSnapshot, ...],
    ) -> dict[tuple[str, int], str]:
        return {(state.source_id, state.generation): state.state.value for state in states}

    @staticmethod
    def _boundary_evidence(
        boundary: str,
        states: tuple[MediaSourceSnapshot, ...],
    ) -> dict[str, Any]:
        return {
            "kind": "source_state_boundary",
            "boundary": boundary,
            "states": [
                {
                    "source_id": state.source_id,
                    "generation": state.generation,
                    "modality": state.modality.value,
                    "source_kind": state.source_kind.value,
                    "state": state.state.value,
                }
                for state in states
            ],
        }

    @classmethod
    def _build_evidence(
        cls,
        temporal: ModelTemporalPart,
    ) -> tuple[dict[str, Any], ...]:
        evidence = [
            observation.to_evidence_dict()
            for temporal_slice in temporal.slices
            for observation in temporal_slice.observations
        ]

        evidence.extend(
            {
                "kind": "source_state_event",
                "event_id": event.event_id,
                "sequence": event.sequence,
                "source_id": event.source_state.source_id,
                "generation": event.source_state.generation,
                "source_kind": event.source_state.source_kind.value,
                "state": event.source_state.state.value,
                "reason": event.source_state.reason,
            }
            for temporal_slice in temporal.slices
            for event in temporal_slice.source_events
            if event.source_state is not None
        )

        alignment = temporal.alignment
        evidence.extend(
            (
                cls._boundary_evidence(
                    "start",
                    alignment.source_states_at_start,
                ),
                cls._boundary_evidence(
                    "end",
                    alignment.source_states_at_end,
                ),
            )
        )

        if alignment.has_event_gap:
            evidence.append(
                {
                    "kind": "perception_event_gap",
                    "missed_event_count": alignment.missed_event_count,
                }
            )

        return tuple(evidence)

    def build(
        self,
        alignment: AlignedPerception,
    ) -> EnvMemoryInput:
        temporal = ModelTemporalPart(
            alignment=alignment,
            slices=self._build_slices(alignment),
        )

        has_media = bool(temporal.observations)
        has_state_events = any(temporal_slice.source_events for temporal_slice in temporal.slices)
        has_boundary_change = self._state_map(alignment.source_states_at_start) != self._state_map(
            alignment.source_states_at_end
        )

        return EnvMemoryInput(
            temporal=temporal,
            evidence=self._build_evidence(temporal),
            has_environment_evidence=(has_media or has_state_events or has_boundary_change),
        )
