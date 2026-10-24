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

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from alphaavatar.agents.avatar.provider.schemas import ModelTemporalPart, ModelTemporalSlice
from alphaavatar.agents.constants import VIDEO_MEMORY_INTERVAL_SEC
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.env.enums import ObservationKind
from alphaavatar.core.env.schemas import PerceptionSourceRef
from alphaavatar.core.perception import AlignedPerception
from alphaavatar.core.perception.schemas import MediaSourceSnapshot


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

    _VISUAL_KINDS = {ObservationKind.VIDEO_FRAME, ObservationKind.SCREEN_FRAME}

    _AUDIO_KINDS = {ObservationKind.AUDIO_FRAME, ObservationKind.AUDIO_SEGMENT}

    def __init__(self, *, include_audio: bool = True) -> None:
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
    def _is_direct_upload(observation: EnvObservation) -> bool:
        return observation.metadata.get("input_origin") == "direct_upload"

    @staticmethod
    def _state_map(states: tuple[MediaSourceSnapshot, ...]) -> dict[PerceptionSourceRef, str]:
        return {state.source: state.state.value for state in states}

    @staticmethod
    def _source_state_evidence(state: MediaSourceSnapshot) -> dict[str, Any]:
        data: dict[str, Any] = {
            "source": state.source.to_dict(),
            "modality": state.modality.value,
            "source_kind": state.source_kind.value,
            "state": state.state.value,
        }

        if state.transport_participant_id is not None:
            data["transport_participant_id"] = state.transport_participant_id

        return data

    @classmethod
    def _boundary_evidence(
        cls, boundary: str, states: tuple[MediaSourceSnapshot, ...]
    ) -> dict[str, Any]:
        return {
            "kind": "source_state_boundary",
            "boundary": boundary,
            "states": [cls._source_state_evidence(state) for state in states],
        }

    @classmethod
    def _build_evidence(cls, temporal: ModelTemporalPart) -> tuple[dict[str, Any], ...]:
        evidence = [
            observation.to_evidence_dict()
            for temporal_slice in temporal.slices
            for observation in temporal_slice.observations
        ]

        for temporal_slice in temporal.slices:
            for event in temporal_slice.source_events:
                state = event.source_state
                if state is None:
                    continue

                item: dict[str, Any] = {
                    "kind": "source_state_event",
                    "event_id": event.event_id,
                    "sequence": event.sequence,
                    "source": state.source.to_dict(),
                    "modality": state.modality.value,
                    "source_kind": state.source_kind.value,
                    "state": state.state.value,
                    "reason": state.reason,
                }

                if state.transport_participant_id is not None:
                    item["transport_participant_id"] = state.transport_participant_id

                evidence.append(item)

        alignment = temporal.alignment

        evidence.extend(
            (
                cls._boundary_evidence("start", alignment.source_states_at_start),
                cls._boundary_evidence("end", alignment.source_states_at_end),
            )
        )

        if alignment.has_event_gap:
            evidence.append(
                {"kind": "perception_event_gap", "missed_event_count": alignment.missed_event_count}
            )

        return tuple(evidence)

    def select_observations(
        self, observations: Iterable[EnvObservation], *, origin_ns: int
    ) -> set[str]:
        observations = {
            item.observation_id: item for item in observations if not self._is_direct_upload(item)
        }
        raw_audio_sources = {
            item.source
            for item in observations.values()
            if item.kind == ObservationKind.AUDIO_FRAME
        }
        buckets: dict[tuple[PerceptionSourceRef, int], EnvObservation] = {}
        selected: set[str] = set()
        for item in sorted(observations.values(), key=self._observation_key):
            if item.kind in self._VISUAL_KINDS:
                bucket = (
                    max(0, item.time_range.end.monotonic_ns - origin_ns) // self._video_interval_ns
                )
                buckets[item.source, bucket] = item
            elif self._include_audio and item.kind in self._AUDIO_KINDS:
                if (
                    item.kind != ObservationKind.AUDIO_SEGMENT
                    or item.source not in raw_audio_sources
                ):
                    selected.add(item.observation_id)
        selected.update(item.observation_id for item in buckets.values())
        return selected

    def _build_slices(
        self, alignment: AlignedPerception, selected_ids: set[str] | None
    ) -> tuple[ModelTemporalSlice, ...]:
        if selected_ids is None:
            selected_ids = self.select_observations(
                (item for part in alignment.slices for item in part.observations),
                origin_ns=alignment.time_range.start.monotonic_ns,
            )

        slices: list[ModelTemporalSlice] = []

        for temporal_slice in alignment.slices:
            selected: dict[str, EnvObservation] = {}

            for observation in temporal_slice.observations:
                if observation.observation_id in selected_ids:
                    selected[observation.observation_id] = observation

            if selected or temporal_slice.source_events:
                slices.append(
                    ModelTemporalSlice(
                        index=temporal_slice.index,
                        time_range=temporal_slice.time_range,
                        observations=tuple(sorted(selected.values(), key=self._observation_key)),
                        source_events=temporal_slice.source_events,
                    )
                )

        return tuple(slices)

    def build(
        self, alignment: AlignedPerception, *, selected_ids: set[str] | None = None
    ) -> EnvMemoryInput:
        temporal = ModelTemporalPart(
            alignment=alignment, slices=self._build_slices(alignment, selected_ids)
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
