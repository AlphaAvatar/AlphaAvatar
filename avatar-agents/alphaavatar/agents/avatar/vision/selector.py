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

from collections import defaultdict

from alphaavatar.agents.configs.plugins.vision_config import VisionConfig
from alphaavatar.agents.providers.schema import ModelInputType
from alphaavatar.core.env import (
    EnvObservation,
    ObservationKind,
    PerceptionSourceRef,
)
from alphaavatar.core.perception import AlignedPerception, TemporalSlice, TemporalSliceKind

from .schema.visual_selection import SelectedVisualFrame, VisualSelection, VisualSliceSelection


class VisualFrameSelector:
    _VISUAL_KINDS = {ObservationKind.VIDEO_FRAME, ObservationKind.SCREEN_FRAME}

    @classmethod
    def _visuals(cls, temporal_slice: TemporalSlice) -> list[EnvObservation]:
        return sorted(
            (
                item
                for item in temporal_slice.observations
                if item.kind in cls._VISUAL_KINDS and item.payload is not None
            ),
            key=lambda item: (item.time_range.end.monotonic_ns, item.observation_id),
        )

    @staticmethod
    def _sample(
        observations: list[EnvObservation],
        *,
        start_ns: int,
        interval_sec: float,
    ) -> list[EnvObservation]:
        interval_ns = max(1, round(interval_sec * 1_000_000_000))
        buckets: dict[tuple[PerceptionSourceRef, int], EnvObservation] = {}
        for observation in observations:
            bucket = max(0, observation.time_range.end.monotonic_ns - start_ns) // interval_ns
            buckets[observation.source, bucket] = observation

        return sorted(
            buckets.values(),
            key=lambda item: (item.time_range.end.monotonic_ns, item.observation_id),
        )

    @staticmethod
    def _build(
        selection: dict[int, list[EnvObservation]], input_type: ModelInputType
    ) -> VisualSelection:
        slices = tuple(
            VisualSliceSelection(
                slice_index=index,
                frames=tuple(
                    SelectedVisualFrame(index, item)
                    for item in sorted(
                        observations,
                        key=lambda item: (item.time_range.end.monotonic_ns, item.observation_id),
                    )
                ),
            )
            for index, observations in sorted(selection.items())
            if observations
        )
        return VisualSelection(input_type=input_type, slices=slices)

    def _select_realtime(
        self, alignment: AlignedPerception, config: VisionConfig
    ) -> VisualSelection:
        selection: dict[int, list[EnvObservation]] = {}
        for temporal_slice in alignment.slices:
            sampled = self._sample(
                self._visuals(temporal_slice),
                start_ns=temporal_slice.time_range.start.monotonic_ns,
                interval_sec=config.sample_interval_sec,
            )
            if sampled:
                selection[temporal_slice.index] = sampled
        return self._build(selection, ModelInputType.REALTIME)

    def _select_flat_vlm(
        self, alignment: AlignedPerception, config: VisionConfig
    ) -> VisualSelection:
        frames: list[tuple[int, EnvObservation]] = []
        for temporal_slice in alignment.slices:
            frames.extend((temporal_slice.index, item) for item in self._visuals(temporal_slice))
        sampled = self._sample(
            [item for _, item in frames],
            start_ns=alignment.time_range.start.monotonic_ns,
            interval_sec=config.sample_interval_sec,
        )
        selected_ids = {item.observation_id for item in sampled[-config.max_frames :]}
        selection: dict[int, list[EnvObservation]] = defaultdict(list)
        for index, observation in frames:
            if observation.observation_id in selected_ids:
                selection[index].append(observation)
        return self._build(selection, ModelInputType.VLM)

    def _select_semantic_vlm(
        self, alignment: AlignedPerception, config: VisionConfig
    ) -> VisualSelection:
        candidates: dict[int, list[EnvObservation]] = {}
        for temporal_slice in alignment.slices:
            if temporal_slice.kind not in {TemporalSliceKind.SPEECH, TemporalSliceKind.GAP}:
                continue
            sampled = self._sample(
                self._visuals(temporal_slice),
                start_ns=temporal_slice.time_range.start.monotonic_ns,
                interval_sec=config.sample_interval_sec,
            )
            if sampled:
                candidates[temporal_slice.index] = sampled

        if not candidates:
            return VisualSelection(input_type=ModelInputType.VLM, slices=())

        selection = {index: [frames[-1]] for index, frames in candidates.items()}
        budget = max(config.max_frames, len(selection))
        remaining = budget - len(selection)
        extras = {index: list(reversed(frames[:-1])) for index, frames in candidates.items()}
        while remaining > 0:
            allocated = False
            for index in sorted(extras):
                if not extras[index] or remaining <= 0:
                    continue
                selection[index].append(extras[index].pop(0))
                remaining -= 1
                allocated = True
            if not allocated:
                break
        return self._build(selection, ModelInputType.VLM)

    def select(self, *, alignment: AlignedPerception, config: VisionConfig) -> VisualSelection:
        if not config.enabled or config.input_mode == ModelInputType.TEXT:
            return VisualSelection(input_type=ModelInputType.TEXT, slices=())

        if config.input_mode == ModelInputType.REALTIME:
            return self._select_realtime(alignment, config)
        if alignment.has_speech_slices:
            return self._select_semantic_vlm(alignment, config)

        return self._select_flat_vlm(alignment, config)
