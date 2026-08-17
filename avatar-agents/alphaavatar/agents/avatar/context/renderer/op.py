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

from dataclasses import replace
from textwrap import indent
from xml.sax.saxutils import escape, quoteattr

from alphaavatar.agents.avatar.context.schema import ContextBuildRequest
from alphaavatar.agents.avatar.vision import (
    SelectedVisualFrame,
    VisualSelection,
)
from alphaavatar.agents.providers.schema import (
    ModelImagePart,
    ModelInput,
    ModelInputMessage,
    ModelInputPart,
    ModelInputType,
    ModelRole,
    ModelTextPart,
)
from alphaavatar.core.env import EnvObservation, ObservationKind
from alphaavatar.core.media import (
    PayloadFormat,
    PayloadFormatUnavailable,
    PayloadView,
)
from alphaavatar.core.perception import (
    AlignedPerception,
    MediaSourceKind,
    MediaSourceSnapshot,
    PerceptionEvent,
    TemporalSlice,
)

_PAUSE_THRESHOLD_SEC = 0.3
_VISUAL_OBSERVATION_KINDS = {
    ObservationKind.VIDEO_FRAME,
    ObservationKind.SCREEN_FRAME,
}


def _xml_attr(value: object) -> str:
    return quoteattr(str(value))


def _xml_text(value: object) -> str:
    return escape(str(value))


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))


def _indent_xml(value: str, spaces: int) -> str:
    return indent(value, " " * spaces)


def _relative_sec(alignment: AlignedPerception, monotonic_ns: int) -> float:
    return (
        max(
            0,
            monotonic_ns - alignment.time_range.start.monotonic_ns,
        )
        / 1_000_000_000
    )


def _relative_label(alignment: AlignedPerception, monotonic_ns: int) -> str:
    return f"+{_relative_sec(alignment, monotonic_ns):.2f}s"


def _range_attrs(alignment: AlignedPerception, temporal_slice: TemporalSlice) -> str:
    return (
        f"start={_xml_attr(_relative_label(alignment, temporal_slice.time_range.start.monotonic_ns))} "
        f"end={_xml_attr(_relative_label(alignment, temporal_slice.time_range.end.monotonic_ns))}"
    )


def _text(observation: EnvObservation | None) -> str | None:
    if observation is None or observation.payload is None:
        return None

    try:
        value = observation.payload.get(
            PayloadFormat.TEXT,
            view=PayloadView.RAW,
            fallback_to_raw=False,
        )
    except PayloadFormatUnavailable:
        return None

    return str(value).strip() or None


def _effective_states(
    states: tuple[MediaSourceSnapshot, ...],
) -> tuple[MediaSourceSnapshot, ...]:
    latest: dict[
        tuple[str, MediaSourceKind],
        MediaSourceSnapshot,
    ] = {}

    for state in states:
        key = state.source_id, state.source_kind
        current = latest.get(key)

        if current is None or state.generation > current.generation:
            latest[key] = state

    return tuple(
        sorted(
            latest.values(),
            key=lambda item: (
                _enum_value(item.source_kind),
                item.source_id,
            ),
        )
    )


def _source_states_xml(
    states: tuple[MediaSourceSnapshot, ...],
    *,
    phase: str,
) -> str:
    effective = _effective_states(states)

    if not effective:
        return f"<source_states phase={_xml_attr(phase)} />"

    lines = [
        f"<source_states phase={_xml_attr(phase)}>",
    ]

    for state in effective:
        lines.append(
            "  <source "
            f"source_id={_xml_attr(state.source_id)} "
            f"generation={_xml_attr(state.generation)} "
            f"modality={_xml_attr(_enum_value(state.modality))} "
            f"kind={_xml_attr(_enum_value(state.source_kind))} "
            f"state={_xml_attr(_enum_value(state.state))} "
            f"available={_xml_attr(str(state.available).lower())} "
            "/>"
        )

    lines.append("</source_states>")
    return "\n".join(lines)


def _perception_integrity_xml(alignment: AlignedPerception) -> str:
    if not alignment.has_event_gap:
        return '<perception_integrity complete="true" missed_event_count="0" />'

    return (
        "<perception_integrity "
        'complete="false" '
        f"missed_event_count={_xml_attr(alignment.missed_event_count)}>\n"
        "  <warning>"
        "Perception events are missing. Do not infer details inside the missing interval. "
        "The start and end source states remain the authoritative boundary facts."
        "</warning>\n"
        "</perception_integrity>"
    )


def _speech_xml(
    temporal_slice: TemporalSlice,
    alignment: AlignedPerception,
    *,
    include_final_gap_after: bool,
) -> str | None:
    speech = temporal_slice.speech

    if speech is None:
        return None

    transcript = _text(speech.transcript)
    lines = [
        "<speech "
        f"source_id={_xml_attr(speech.source_id)} "
        f"segment_id={_xml_attr(speech.segment_id)} "
        f"start={_xml_attr(_relative_label(alignment, speech.time_range.start.monotonic_ns))} "
        f"end={_xml_attr(_relative_label(alignment, speech.time_range.end.monotonic_ns))} "
        f"audio_available={_xml_attr(str(speech.speech is not None).lower())}>"
    ]

    if temporal_slice.gap_before_sec >= _PAUSE_THRESHOLD_SEC:
        lines.append(
            f"  <speech_gap_before seconds={_xml_attr(f'{temporal_slice.gap_before_sec:.2f}')} />"
        )

    if transcript:
        lines.append(f"  <transcript>{_xml_text(transcript)}</transcript>")
    else:
        lines.append('  <transcript available="false" />')

    if include_final_gap_after and temporal_slice.gap_after_sec >= _PAUSE_THRESHOLD_SEC:
        lines.append(
            "  <speech_gap_after "
            f"seconds={_xml_attr(f'{temporal_slice.gap_after_sec:.2f}')} "
            'relation="before_direct_input_or_turn_end" '
            "/>"
        )

    lines.append("</speech>")
    return "\n".join(lines)


def _source_event_xml(event: PerceptionEvent, alignment: AlignedPerception) -> str:
    state = event.source_state

    if state is None:
        return ""

    attributes = [
        f"at={_xml_attr(_relative_label(alignment, event.time_range.end.monotonic_ns))}",
        f"source_id={_xml_attr(state.source_id)}",
        f"generation={_xml_attr(state.generation)}",
        f"modality={_xml_attr(_enum_value(state.modality))}",
        f"kind={_xml_attr(_enum_value(state.source_kind))}",
        f"state={_xml_attr(_enum_value(state.state))}",
    ]

    if state.reason:
        attributes.append(f"reason={_xml_attr(state.reason)}")

    return f"<source_event {' '.join(attributes)} />"


def _visual_availability_xml(
    alignment: AlignedPerception,
    visual_selection: VisualSelection,
    *,
    model_input_type: ModelInputType,
) -> str:
    states = _effective_states(alignment.source_states_at_end)
    visual_states = [
        state
        for state in states
        if state.source_kind
        in {
            MediaSourceKind.CAMERA,
            MediaSourceKind.SCREEN,
        }
    ]
    active_states = [state for state in visual_states if state.available]
    active_keys = {(state.source_id, state.generation) for state in active_states}

    selected_keys = set()

    for frame in visual_selection.frames:
        generation = frame.observation.metadata.get("source_generation")

        if isinstance(generation, int):
            selected_keys.add(
                (
                    frame.observation.source_id,
                    generation,
                )
            )

    has_matching_evidence = bool(active_keys.intersection(selected_keys))

    if model_input_type == ModelInputType.TEXT and active_states:
        status = "active_without_model_visual_evidence"
        live = True
        meaning = (
            "A live visual source remained active at input end, "
            "but this text-only model input cannot inspect visual media."
        )

    elif active_states and has_matching_evidence:
        status = "active_with_sampled_evidence"
        live = True
        meaning = (
            "Live visual input remained active at input end. "
            "Selected images are sampled evidence from the active source generation, "
            "not a guaranteed instantaneous view."
        )

    elif active_states and not visual_selection.empty:
        status = "active_with_historical_or_other_generation_evidence"
        live = True
        meaning = (
            "Live visual input remained active at input end, "
            "but selected images do not belong to the active source generation. "
            "Do not use them as the current view."
        )

    elif active_states:
        status = "active_without_sampled_evidence"
        live = True
        meaning = (
            "Live visual input remained active at input end, "
            "but no selected image from the active source generation is available. "
            "Do not guess what is visible."
        )

    elif visual_states:
        status = "unavailable_at_input_end"
        live = False
        meaning = (
            "No live camera or screen input was available at input end. "
            "Earlier selected images are historical evidence only."
        )

    else:
        status = "no_visual_source"
        live = False
        meaning = "No camera or screen source was present at input end."

    return (
        "<visual_availability "
        f"status={_xml_attr(status)} "
        f"live={_xml_attr(str(live).lower())}>"
        f"{_xml_text(meaning)}"
        "</visual_availability>"
    )


def _visual_observation_count(temporal_slice: TemporalSlice) -> int:
    return sum(
        observation.kind in _VISUAL_OBSERVATION_KINDS for observation in temporal_slice.observations
    )


def _last_speech_slice_index(alignment: AlignedPerception) -> int | None:
    return next(
        (
            temporal_slice.index
            for temporal_slice in reversed(alignment.slices)
            if temporal_slice.speech is not None
        ),
        None,
    )


def _slice_open_xml(
    temporal_slice: TemporalSlice,
    alignment: AlignedPerception,
    *,
    include_final_gap_after: bool,
) -> str:
    lines = [
        "    <slice "
        f"index={_xml_attr(temporal_slice.index)} "
        f"kind={_xml_attr(temporal_slice.kind.value)} "
        f"{_range_attrs(alignment, temporal_slice)}>"
    ]

    speech_xml = _speech_xml(
        temporal_slice,
        alignment,
        include_final_gap_after=include_final_gap_after,
    )

    if speech_xml:
        lines.append(_indent_xml(speech_xml, 6))

    return "\n".join(lines)


def _ordered_slice_parts(
    *,
    temporal_slice: TemporalSlice,
    alignment: AlignedPerception,
    frames: tuple[SelectedVisualFrame, ...],
) -> tuple[ModelInputPart, ...]:
    entries: list[tuple[int, int, tuple[ModelInputPart, ...]]] = []

    for event in temporal_slice.source_events:
        event_xml = _source_event_xml(
            event,
            alignment,
        )

        if event_xml:
            entries.append(
                (
                    event.time_range.end.monotonic_ns,
                    0,
                    (
                        ModelTextPart(
                            _indent_xml(
                                event_xml,
                                6,
                            )
                        ),
                    ),
                )
            )

    for frame in frames:
        observation = frame.observation
        generation = observation.metadata.get("source_generation")

        attributes = [
            f"observation_id={_xml_attr(observation.observation_id)}",
            f"source_id={_xml_attr(observation.source_id)}",
            f"kind={_xml_attr(_enum_value(observation.kind))}",
            f"captured_at={_xml_attr(_relative_label(alignment, observation.time_range.end.monotonic_ns))}",
            'sampled="true"',
        ]

        if isinstance(generation, int):
            attributes.append(f"source_generation={_xml_attr(generation)}")

        entries.append(
            (
                observation.time_range.end.monotonic_ns,
                1,
                (
                    ModelTextPart(
                        _indent_xml(
                            f"<visual_evidence {' '.join(attributes)}>",
                            6,
                        )
                    ),
                    ModelImagePart(observation),
                    ModelTextPart(
                        _indent_xml(
                            "</visual_evidence>",
                            6,
                        )
                    ),
                ),
            )
        )

    parts: list[ModelInputPart] = []

    for _, _, entry_parts in sorted(
        entries,
        key=lambda entry: (
            entry[0],
            entry[1],
        ),
    ):
        parts.extend(entry_parts)

    return tuple(parts)


def _direct_input_parts(
    alignment: AlignedPerception,
    *,
    include_images: bool,
) -> tuple[ModelInputPart, ...]:
    if not alignment.direct_inputs:
        return (ModelTextPart("  <direct_inputs />"),)

    parts: list[ModelInputPart] = [
        ModelTextPart("  <direct_inputs>"),
    ]

    for index, observation in enumerate(alignment.direct_inputs):
        common_attributes = (
            f"index={_xml_attr(index)} "
            f"observation_id={_xml_attr(observation.observation_id)} "
            f"source_id={_xml_attr(observation.source_id)}"
        )

        if observation.kind == ObservationKind.TEXT_INPUT:
            value = _text(observation)

            if value:
                parts.append(
                    ModelTextPart(
                        f"    <text_input {common_attributes}>{_xml_text(value)}</text_input>"
                    )
                )

        elif observation.kind == ObservationKind.IMAGE_INPUT:
            if include_images:
                parts.extend(
                    (
                        ModelTextPart(f"    <image_input {common_attributes}>"),
                        ModelImagePart(observation),
                        ModelTextPart("    </image_input>"),
                    )
                )
            else:
                parts.append(
                    ModelTextPart(f'    <image_input {common_attributes} inspectable="false" />')
                )

        else:
            parts.append(
                ModelTextPart(
                    "    <direct_input "
                    f"{common_attributes} "
                    f"kind={_xml_attr(_enum_value(observation.kind))} "
                    "/>"
                )
            )

    parts.append(ModelTextPart("  </direct_inputs>"))
    return tuple(parts)


def replace_current(
    base_input: ModelInput,
    input_id: str,
    parts: tuple[ModelInputPart, ...],
) -> ModelInput:
    current = base_input.get(input_id)

    if isinstance(current, ModelInputMessage):
        return base_input.replace(
            input_id,
            replace(
                current,
                parts=parts,
            ),
        )

    return base_input.append(
        ModelInputMessage(
            id=input_id,
            role=ModelRole.USER,
            parts=parts,
        )
    )


def render_current_input(
    request: ContextBuildRequest,
    *,
    include_images: bool,
) -> tuple[ModelInputPart, ...]:
    alignment = request.alignment
    duration_label = _relative_label(
        alignment,
        alignment.time_range.end.monotonic_ns,
    )

    parts: list[ModelInputPart] = [
        ModelTextPart(
            "<turn_input "
            f"input_id={_xml_attr(request.input_id)} "
            f"alignment={_xml_attr(alignment.mode.value)} "
            'start="+0.00s" '
            f"end={_xml_attr(duration_label)}>"
        ),
        ModelTextPart(
            _indent_xml(
                _perception_integrity_xml(alignment),
                2,
            )
        ),
        ModelTextPart(
            _indent_xml(
                _source_states_xml(
                    alignment.source_states_at_start,
                    phase="start",
                ),
                2,
            )
        ),
        ModelTextPart("  <timeline>"),
    ]

    last_speech_index = _last_speech_slice_index(alignment)

    for temporal_slice in alignment.slices:
        frames = request.visual_selection.for_slice(temporal_slice.index) if include_images else ()
        visual_count = _visual_observation_count(temporal_slice)

        if (
            temporal_slice.speech is None
            and not temporal_slice.source_events
            and not frames
            and not (not include_images and visual_count)
        ):
            continue

        parts.append(
            ModelTextPart(
                _slice_open_xml(
                    temporal_slice,
                    alignment,
                    include_final_gap_after=(temporal_slice.index == last_speech_index),
                )
            )
        )

        if include_images:
            parts.extend(
                _ordered_slice_parts(
                    temporal_slice=temporal_slice,
                    alignment=alignment,
                    frames=frames,
                )
            )
        else:
            for event in temporal_slice.source_events:
                event_xml = _source_event_xml(
                    event,
                    alignment,
                )

                if event_xml:
                    parts.append(ModelTextPart(_indent_xml(event_xml, 6)))

            if visual_count:
                parts.append(
                    ModelTextPart(
                        "      <visual_evidence "
                        'available_to_model="false" '
                        f"count={_xml_attr(visual_count)} "
                        "/>"
                    )
                )

        parts.append(ModelTextPart("    </slice>"))

    parts.extend(
        (
            ModelTextPart("  </timeline>"),
            ModelTextPart(
                _indent_xml(
                    _source_states_xml(
                        alignment.source_states_at_end,
                        phase="end",
                    ),
                    2,
                )
            ),
            ModelTextPart(
                _indent_xml(
                    _visual_availability_xml(
                        alignment,
                        request.visual_selection,
                        model_input_type=request.model_input_type,
                    ),
                    2,
                )
            ),
        )
    )

    parts.extend(
        _direct_input_parts(
            alignment,
            include_images=include_images,
        )
    )
    parts.append(ModelTextPart("</turn_input>"))

    return tuple(parts)
