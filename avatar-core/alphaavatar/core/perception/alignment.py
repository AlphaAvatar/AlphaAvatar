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

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from math import ceil, floor

from alphaavatar.core.env import EnvObservation, ObservationKind
from alphaavatar.core.time import RuntimeTime, RuntimeTimeRange

from .event import MediaSourceSnapshot, PerceptionEvent


class TemporalAlignmentMode(StrEnum):
    AUTO = "auto"
    FIXED = "fixed"
    SPEECH_ANCHORED = "speech_anchored"


class TemporalSliceKind(StrEnum):
    FIXED = "fixed"
    SPEECH = "speech"
    GAP = "gap"


@dataclass(frozen=True, slots=True)
class TemporalAlignmentPolicy:
    mode: TemporalAlignmentMode = TemporalAlignmentMode.AUTO
    interval_sec: float = 1.0
    min_interval_sec: float = 0.5
    max_interval_sec: float = 2.0
    speech_context_sec: float = 0.5
    include_gap_slices: bool = True

    def __post_init__(self) -> None:
        if self.min_interval_sec <= 0:
            raise ValueError("min_interval_sec must be positive")

        if self.max_interval_sec < self.min_interval_sec:
            raise ValueError("max_interval_sec cannot be smaller than min_interval_sec")

        if not self.min_interval_sec <= self.interval_sec <= self.max_interval_sec:
            raise ValueError("interval_sec must be between min_interval_sec and max_interval_sec")

        if self.speech_context_sec < 0:
            raise ValueError("speech_context_sec cannot be negative")


@dataclass(frozen=True, slots=True)
class AlignedSpeechSegment:
    source_id: str
    segment_id: str
    time_range: RuntimeTimeRange
    speech: EnvObservation | None = None
    transcript: EnvObservation | None = None

    @property
    def observations(self) -> tuple[EnvObservation, ...]:
        return tuple(item for item in (self.speech, self.transcript) if item is not None)


@dataclass(frozen=True, slots=True)
class TemporalSlice:
    index: int
    kind: TemporalSliceKind
    time_range: RuntimeTimeRange
    observations: tuple[EnvObservation, ...]
    source_events: tuple[PerceptionEvent, ...]
    speech: AlignedSpeechSegment | None = None
    gap_before_sec: float = 0.0
    gap_after_sec: float = 0.0

    @property
    def empty(self) -> bool:
        return not self.observations and not self.source_events


@dataclass(frozen=True, slots=True)
class AlignedPerception:
    mode: TemporalAlignmentMode
    time_range: RuntimeTimeRange
    slices: tuple[TemporalSlice, ...]
    direct_inputs: tuple[EnvObservation, ...]
    source_states_at_start: tuple[MediaSourceSnapshot, ...]
    source_states_at_end: tuple[MediaSourceSnapshot, ...]
    has_event_gap: bool = False
    missed_event_count: int = 0

    @property
    def empty(self) -> bool:
        return not self.slices and not self.direct_inputs

    @property
    def has_speech_slices(self) -> bool:
        return any(item.kind == TemporalSliceKind.SPEECH for item in self.slices)


@dataclass(slots=True)
class _SpeechGroup:
    source_id: str
    segment_id: str
    speech: EnvObservation | None = None
    transcript: EnvObservation | None = None


@dataclass(slots=True)
class _SliceDraft:
    kind: TemporalSliceKind
    time_range: RuntimeTimeRange
    observations: list[EnvObservation]
    source_events: list[PerceptionEvent]
    speech: AlignedSpeechSegment | None = None
    gap_before_sec: float = 0.0
    gap_after_sec: float = 0.0

    @property
    def empty(self) -> bool:
        return not self.observations and not self.source_events


class PerceptionTemporalAligner:
    """
    Build one provider-neutral multimodal timeline.

    FIXED:
        Split the requested range into bounded intervals. Point observations
        enter one interval; ranged observations enter every overlapping interval.

    SPEECH_ANCHORED:
        Each VAD speech segment becomes one semantic slice. A transcript with
        the same speech source and segment_id is attached to that slice.
        Evidence between speech windows becomes non-empty GAP slices.

    AUTO:
        Use SPEECH_ANCHORED when at least one speech/transcript segment exists;
        otherwise use FIXED.

    The aligner does not filter observation kinds. Producers and consumers
    decide which observations should be supplied.
    """

    _DIRECT_INPUT_KINDS = {
        ObservationKind.TEXT_INPUT,
        ObservationKind.IMAGE_INPUT,
    }

    def __init__(self, policy: TemporalAlignmentPolicy | None = None) -> None:
        self.policy = policy or TemporalAlignmentPolicy()

    """Sort operations"""

    @staticmethod
    def _observation_key(observation: EnvObservation) -> tuple[int, int, int, str]:
        content_index = observation.metadata.get("content_index", 0)

        return (
            observation.time_range.start.monotonic_ns,
            observation.time_range.end.monotonic_ns,
            content_index if isinstance(content_index, int) else 0,
            observation.observation_id,
        )

    @staticmethod
    def _event_key(event: PerceptionEvent) -> tuple[int, int]:
        return event.time_range.start.monotonic_ns, event.sequence

    @staticmethod
    def _source_state_key(state: MediaSourceSnapshot) -> tuple[str, str, str, int]:
        modality = getattr(state.modality, "value", state.modality)
        source_kind = getattr(state.source_kind, "value", state.source_kind)

        return (
            str(modality),
            str(source_kind),
            state.source_id,
            state.generation,
        )

    """Time operations"""

    @staticmethod
    def _time_at(start: RuntimeTime, offset_ns: int) -> RuntimeTime:
        return RuntimeTime(
            unix_ns=start.unix_ns + offset_ns,
            monotonic_ns=start.monotonic_ns + offset_ns,
        )

    @staticmethod
    def _duration(start: RuntimeTime, end: RuntimeTime) -> float:
        return (
            max(
                0,
                end.monotonic_ns - start.monotonic_ns,
            )
            / 1_000_000_000
        )

    @staticmethod
    def _boundary(
        left: RuntimeTime,
        right: RuntimeTime,
    ) -> RuntimeTime:
        if right.monotonic_ns <= left.monotonic_ns:
            return right

        return PerceptionTemporalAligner._time_at(
            left,
            (right.monotonic_ns - left.monotonic_ns) // 2,
        )

    @staticmethod
    def _midpoint_ns(
        time_range: RuntimeTimeRange,
    ) -> int:
        return (time_range.start.monotonic_ns + time_range.end.monotonic_ns) // 2

    @staticmethod
    def _is_point(time_range: RuntimeTimeRange) -> bool:
        return time_range.start.monotonic_ns == time_range.end.monotonic_ns

    @staticmethod
    def _contains_point(
        time_range: RuntimeTimeRange,
        at_ns: int,
        *,
        include_end: bool = False,
    ) -> bool:
        start = time_range.start.monotonic_ns
        end = time_range.end.monotonic_ns

        if include_end:
            return start <= at_ns <= end

        return start <= at_ns < end

    @classmethod
    def _overlaps(
        cls,
        left: RuntimeTimeRange,
        right: RuntimeTimeRange,
    ) -> bool:
        """
        Test temporal overlap using half-open interval semantics.

        Normal ranges use:
            [start, end)

        Point ranges are matched explicitly and may match the final boundary.
        """
        if cls._is_point(left):
            return cls._contains_point(
                right,
                left.start.monotonic_ns,
                include_end=True,
            )

        if cls._is_point(right):
            return cls._contains_point(
                left,
                right.start.monotonic_ns,
                include_end=True,
            )

        return (
            left.start.monotonic_ns < right.end.monotonic_ns
            and right.start.monotonic_ns < left.end.monotonic_ns
        )

    @staticmethod
    def _distance(at_ns: int, time_range: RuntimeTimeRange) -> int:
        if at_ns < time_range.start.monotonic_ns:
            return time_range.start.monotonic_ns - at_ns

        if at_ns > time_range.end.monotonic_ns:
            return at_ns - time_range.end.monotonic_ns

        return 0

    """Input normalization"""

    def _normalize(
        self,
        observations: Sequence[EnvObservation],
        events: Sequence[PerceptionEvent],
    ) -> tuple[list[EnvObservation], list[PerceptionEvent]]:
        by_id = {item.observation_id: item for item in observations}
        source_events: list[PerceptionEvent] = []

        for event in events:
            if event.observation is not None:
                by_id.setdefault(
                    event.observation.observation_id,
                    event.observation,
                )

            elif event.source_state is not None:
                source_events.append(event)

        return (
            sorted(
                by_id.values(),
                key=self._observation_key,
            ),
            sorted(
                source_events,
                key=self._event_key,
            ),
        )

    @staticmethod
    def _resolve_range(
        time_range: RuntimeTimeRange | None,
        observations: Sequence[EnvObservation],
        source_events: Sequence[PerceptionEvent],
    ) -> RuntimeTimeRange:
        if time_range is not None:
            return time_range

        ranges = [item.time_range for item in observations]
        ranges.extend(item.time_range for item in source_events)

        if not ranges:
            raise ValueError("time_range is required when no temporal evidence exists")

        return RuntimeTimeRange(
            start=min(
                ranges,
                key=lambda item: item.start.monotonic_ns,
            ).start,
            end=max(
                ranges,
                key=lambda item: item.end.monotonic_ns,
            ).end,
        )

    """Fixed alignment"""

    def _partition(
        self,
        time_range: RuntimeTimeRange,
    ) -> tuple[RuntimeTimeRange, ...]:
        duration_ns = time_range.end.monotonic_ns - time_range.start.monotonic_ns

        if duration_ns <= 0:
            return (time_range,)

        duration_sec = duration_ns / 1_000_000_000

        target_count = max(
            1,
            ceil(duration_sec / self.policy.interval_sec),
        )
        minimum_count = max(
            1,
            ceil(duration_sec / self.policy.max_interval_sec),
        )
        maximum_count = max(
            1,
            floor(duration_sec / self.policy.min_interval_sec),
        )

        count = max(target_count, minimum_count)

        if maximum_count >= minimum_count:
            count = min(
                count,
                maximum_count,
            )

        return tuple(
            RuntimeTimeRange(
                start=self._time_at(
                    time_range.start,
                    duration_ns * index // count,
                ),
                end=(
                    time_range.end
                    if index == count - 1
                    else self._time_at(
                        time_range.start,
                        duration_ns * (index + 1) // count,
                    )
                ),
            )
            for index in range(count)
        )

    @staticmethod
    def _point_slice_index(
        ranges: Sequence[RuntimeTimeRange],
        at_ns: int,
    ) -> int:
        """
        Assign a point to one fixed slice.

        Slice boundaries use [start, end), except that the final boundary is
        assigned to the final slice.
        """
        for index, time_range in enumerate(ranges):
            if at_ns < time_range.end.monotonic_ns:
                return index

        return len(ranges) - 1

    def _observation_slice_indices(
        self,
        ranges: Sequence[RuntimeTimeRange],
        observation: EnvObservation,
    ) -> tuple[int, ...]:
        if self._is_point(observation.time_range):
            return (
                self._point_slice_index(
                    ranges,
                    observation.time_range.end.monotonic_ns,
                ),
            )

        indices = tuple(
            index
            for index, time_range in enumerate(ranges)
            if self._overlaps(
                observation.time_range,
                time_range,
            )
        )

        if indices:
            return indices

        return (
            self._point_slice_index(
                ranges,
                self._midpoint_ns(observation.time_range),
            ),
        )

    def _fixed_drafts(
        self,
        *,
        time_range: RuntimeTimeRange,
        observations: Sequence[EnvObservation],
        source_events: Sequence[PerceptionEvent],
        kind: TemporalSliceKind,
    ) -> list[_SliceDraft]:
        ranges = self._partition(time_range)

        observation_groups: list[list[EnvObservation]] = [[] for _ in ranges]
        event_groups: list[list[PerceptionEvent]] = [[] for _ in ranges]

        for observation in observations:
            for index in self._observation_slice_indices(
                ranges,
                observation,
            ):
                observation_groups[index].append(observation)

        for event in source_events:
            index = self._point_slice_index(
                ranges,
                event.time_range.end.monotonic_ns,
            )
            event_groups[index].append(event)

        return [
            _SliceDraft(
                kind=kind,
                time_range=item,
                observations=observation_groups[index],
                source_events=event_groups[index],
            )
            for index, item in enumerate(ranges)
            if observation_groups[index] or event_groups[index]
        ]

    """Speech alignment"""

    @staticmethod
    def _segment_key(
        observation: EnvObservation,
    ) -> tuple[str, str] | None:
        segment_id = getattr(observation, "segment_id", None)
        segment_id = segment_id or observation.metadata.get("segment_id")

        source_id = observation.metadata.get("speech_source_id") or observation.source_id

        if not source_id or not segment_id:
            return None

        return str(source_id), str(segment_id)

    def _speech_segments(
        self,
        observations: Sequence[EnvObservation],
    ) -> tuple[AlignedSpeechSegment, ...]:
        groups: dict[tuple[str, str], _SpeechGroup] = {}

        for observation in observations:
            if observation.kind not in {
                ObservationKind.SPEECH_SEGMENT,
                ObservationKind.TRANSCRIPT_SEGMENT,
            }:
                continue

            key = self._segment_key(observation)

            if key is None:
                continue

            group = groups.setdefault(
                key,
                _SpeechGroup(
                    source_id=key[0],
                    segment_id=key[1],
                ),
            )

            if observation.kind == ObservationKind.SPEECH_SEGMENT:
                group.speech = observation
            else:
                group.transcript = observation

        segments: list[AlignedSpeechSegment] = []

        for group in groups.values():
            anchor = group.speech or group.transcript

            if anchor is None:
                continue

            segments.append(
                AlignedSpeechSegment(
                    source_id=group.source_id,
                    segment_id=group.segment_id,
                    time_range=anchor.time_range,
                    speech=group.speech,
                    transcript=group.transcript,
                )
            )

        return tuple(
            sorted(
                segments,
                key=lambda item: (
                    item.time_range.start.monotonic_ns,
                    item.time_range.end.monotonic_ns,
                    item.source_id,
                    item.segment_id,
                ),
            )
        )

    def _speech_windows(
        self,
        segments: Sequence[AlignedSpeechSegment],
        time_range: RuntimeTimeRange,
    ) -> tuple[RuntimeTimeRange, ...]:
        windows: list[RuntimeTimeRange] = []
        context_sec = self.policy.speech_context_sec

        for index, segment in enumerate(segments):
            previous = segments[index - 1] if index else None
            following = segments[index + 1] if index + 1 < len(segments) else None

            left_limit = (
                self._boundary(
                    previous.time_range.end,
                    segment.time_range.start,
                )
                if previous is not None
                and previous.time_range.end.monotonic_ns < segment.time_range.start.monotonic_ns
                else segment.time_range.start
            )

            right_limit = (
                self._boundary(
                    segment.time_range.end,
                    following.time_range.start,
                )
                if following is not None
                and segment.time_range.end.monotonic_ns < following.time_range.start.monotonic_ns
                else segment.time_range.end
            )

            if previous is None:
                left_limit = time_range.start

            if following is None:
                right_limit = time_range.end

            requested_start = segment.time_range.start.shifted(-context_sec)
            requested_end = segment.time_range.end.shifted(context_sec)

            start = max(
                time_range.start,
                left_limit,
                requested_start,
                key=lambda item: item.monotonic_ns,
            )
            end = min(
                time_range.end,
                right_limit,
                requested_end,
                key=lambda item: item.monotonic_ns,
            )

            if end.monotonic_ns < start.monotonic_ns:
                end = start

            windows.append(
                RuntimeTimeRange(
                    start=start,
                    end=end,
                )
            )

        return tuple(windows)

    @staticmethod
    def _merged_windows(
        windows: Sequence[RuntimeTimeRange],
    ) -> tuple[RuntimeTimeRange, ...]:
        merged: list[RuntimeTimeRange] = []

        for window in sorted(
            windows,
            key=lambda item: item.start.monotonic_ns,
        ):
            if not merged or window.start.monotonic_ns > merged[-1].end.monotonic_ns:
                merged.append(window)
                continue

            previous = merged[-1]

            end = (
                window.end if window.end.monotonic_ns > previous.end.monotonic_ns else previous.end
            )

            merged[-1] = RuntimeTimeRange(
                start=previous.start,
                end=end,
            )

        return tuple(merged)

    def _gap_ranges(
        self,
        time_range: RuntimeTimeRange,
        windows: Sequence[RuntimeTimeRange],
    ) -> tuple[RuntimeTimeRange, ...]:
        cursor = time_range.start
        gaps: list[RuntimeTimeRange] = []

        for window in self._merged_windows(windows):
            if window.start.monotonic_ns > cursor.monotonic_ns:
                gaps.append(
                    RuntimeTimeRange(
                        start=cursor,
                        end=window.start,
                    )
                )

            if window.end.monotonic_ns > cursor.monotonic_ns:
                cursor = window.end

        if cursor.monotonic_ns < time_range.end.monotonic_ns:
            gaps.append(
                RuntimeTimeRange(
                    start=cursor,
                    end=time_range.end,
                )
            )

        return tuple(gaps)

    @staticmethod
    def _draft_anchor(draft: _SliceDraft) -> RuntimeTimeRange:
        if draft.speech is not None:
            return draft.speech.time_range

        return draft.time_range

    def _point_draft_index(
        self,
        drafts: Sequence[_SliceDraft],
        at_ns: int,
        *,
        overall_end_ns: int,
    ) -> int | None:
        matches = [
            index
            for index, draft in enumerate(drafts)
            if self._contains_point(
                draft.time_range,
                at_ns,
                include_end=(draft.time_range.end.monotonic_ns == overall_end_ns),
            )
        ]

        if matches:
            return min(
                matches,
                key=lambda index: (
                    self._distance(
                        at_ns,
                        self._draft_anchor(drafts[index]),
                    ),
                    (0 if drafts[index].kind == TemporalSliceKind.SPEECH else 1),
                    index,
                ),
            )

        if not drafts:
            return None

        return min(
            range(len(drafts)),
            key=lambda index: (
                self._distance(
                    at_ns,
                    self._draft_anchor(drafts[index]),
                ),
                index,
            ),
        )

    def _observation_draft_indices(
        self,
        drafts: Sequence[_SliceDraft],
        observation: EnvObservation,
        *,
        overall_end_ns: int,
    ) -> tuple[int, ...]:
        if self._is_point(observation.time_range):
            index = self._point_draft_index(
                drafts,
                observation.time_range.end.monotonic_ns,
                overall_end_ns=overall_end_ns,
            )

            return () if index is None else (index,)

        indices = tuple(
            index
            for index, draft in enumerate(drafts)
            if self._overlaps(
                observation.time_range,
                draft.time_range,
            )
        )

        if indices:
            return indices

        index = self._point_draft_index(
            drafts,
            self._midpoint_ns(observation.time_range),
            overall_end_ns=overall_end_ns,
        )

        return () if index is None else (index,)

    def _speech_drafts(
        self,
        *,
        time_range: RuntimeTimeRange,
        observations: Sequence[EnvObservation],
        source_events: Sequence[PerceptionEvent],
        segments: Sequence[AlignedSpeechSegment],
    ) -> list[_SliceDraft]:
        if not segments:
            return self._fixed_drafts(
                time_range=time_range,
                observations=observations,
                source_events=source_events,
                kind=TemporalSliceKind.FIXED,
            )

        windows = self._speech_windows(segments, time_range)

        drafts: list[_SliceDraft] = []

        for index, segment in enumerate(segments):
            previous = segments[index - 1] if index else None
            following = segments[index + 1] if index + 1 < len(segments) else None

            drafts.append(
                _SliceDraft(
                    kind=TemporalSliceKind.SPEECH,
                    time_range=windows[index],
                    observations=list(segment.observations),
                    source_events=[],
                    speech=segment,
                    gap_before_sec=self._duration(
                        (previous.time_range.end if previous is not None else time_range.start),
                        segment.time_range.start,
                    ),
                    gap_after_sec=self._duration(
                        segment.time_range.end,
                        (following.time_range.start if following is not None else time_range.end),
                    ),
                )
            )

        if self.policy.include_gap_slices:
            for gap in self._gap_ranges(time_range, windows):
                drafts.extend(
                    _SliceDraft(
                        kind=TemporalSliceKind.GAP,
                        time_range=item,
                        observations=[],
                        source_events=[],
                    )
                    for item in self._partition(gap)
                )

        segment_observation_ids = {
            item.observation_id for segment in segments for item in segment.observations
        }

        for observation in observations:
            if observation.observation_id in segment_observation_ids:
                continue

            indices = self._observation_draft_indices(
                drafts,
                observation,
                overall_end_ns=time_range.end.monotonic_ns,
            )

            for index in indices:
                drafts[index].observations.append(observation)

        for event in source_events:
            index = self._point_draft_index(
                drafts,
                event.time_range.end.monotonic_ns,
                overall_end_ns=time_range.end.monotonic_ns,
            )

            if index is not None:
                drafts[index].source_events.append(event)

        return drafts

    """Finalization"""

    def _finalize(self, drafts: Sequence[_SliceDraft]) -> tuple[TemporalSlice, ...]:
        ordered = sorted(
            (
                draft
                for draft in drafts
                if (draft.kind == TemporalSliceKind.SPEECH or not draft.empty)
            ),
            key=lambda item: (
                item.time_range.start.monotonic_ns,
                item.time_range.end.monotonic_ns,
                item.kind.value,
            ),
        )

        return tuple(
            TemporalSlice(
                index=index,
                kind=draft.kind,
                time_range=draft.time_range,
                observations=tuple(
                    sorted(
                        draft.observations,
                        key=self._observation_key,
                    )
                ),
                source_events=tuple(
                    sorted(
                        draft.source_events,
                        key=self._event_key,
                    )
                ),
                speech=draft.speech,
                gap_before_sec=draft.gap_before_sec,
                gap_after_sec=draft.gap_after_sec,
            )
            for index, draft in enumerate(ordered)
        )

    """Public API"""

    def align(
        self,
        *,
        events: Sequence[PerceptionEvent] = (),
        observations: Sequence[EnvObservation] = (),
        time_range: RuntimeTimeRange | None = None,
        source_states_at_start: Sequence[MediaSourceSnapshot] = (),
        source_states_at_end: Sequence[MediaSourceSnapshot] = (),
        mode: TemporalAlignmentMode | None = None,
        has_event_gap: bool = False,
        missed_event_count: int = 0,
    ) -> AlignedPerception:
        if missed_event_count < 0:
            raise ValueError("missed_event_count cannot be negative")

        normalized, source_events = self._normalize(
            observations,
            events,
        )

        resolved_range = self._resolve_range(
            time_range,
            normalized,
            source_events,
        )

        # Ignore evidence outside the requested alignment window instead of
        # forcing it into the first or final slice.
        normalized = [
            item
            for item in normalized
            if self._overlaps(
                item.time_range,
                resolved_range,
            )
        ]

        source_events = [
            item
            for item in source_events
            if self._contains_point(
                resolved_range,
                item.time_range.end.monotonic_ns,
                include_end=True,
            )
        ]

        direct_inputs = tuple(item for item in normalized if item.kind in self._DIRECT_INPUT_KINDS)

        temporal_observations = [
            item for item in normalized if item.kind not in self._DIRECT_INPUT_KINDS
        ]

        speech_segments = self._speech_segments(temporal_observations)

        resolved_mode = mode or self.policy.mode

        if resolved_mode == TemporalAlignmentMode.AUTO:
            resolved_mode = (
                TemporalAlignmentMode.SPEECH_ANCHORED
                if speech_segments
                else TemporalAlignmentMode.FIXED
            )

        elif resolved_mode == TemporalAlignmentMode.SPEECH_ANCHORED and not speech_segments:
            resolved_mode = TemporalAlignmentMode.FIXED

        if resolved_mode == TemporalAlignmentMode.SPEECH_ANCHORED:
            drafts = self._speech_drafts(
                time_range=resolved_range,
                observations=temporal_observations,
                source_events=source_events,
                segments=speech_segments,
            )
        else:
            drafts = self._fixed_drafts(
                time_range=resolved_range,
                observations=temporal_observations,
                source_events=source_events,
                kind=TemporalSliceKind.FIXED,
            )

        return AlignedPerception(
            mode=resolved_mode,
            time_range=resolved_range,
            slices=self._finalize(drafts),
            direct_inputs=tuple(
                sorted(
                    direct_inputs,
                    key=self._observation_key,
                )
            ),
            source_states_at_start=tuple(
                sorted(
                    source_states_at_start,
                    key=self._source_state_key,
                )
            ),
            source_states_at_end=tuple(
                sorted(
                    source_states_at_end,
                    key=self._source_state_key,
                )
            ),
            has_event_gap=(has_event_gap or missed_event_count > 0),
            missed_event_count=missed_event_count,
        )
