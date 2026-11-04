# Copyright 2025 AlphaAvatar project
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
from dataclasses import dataclass
from xml.sax.saxutils import escape, quoteattr

from alphaavatar.agents.avatar.provider.enums import ModelTextPartKind
from alphaavatar.agents.avatar.provider.schemas import ModelTextPart
from alphaavatar.core.env.enums import ObservationKind
from alphaavatar.core.turn.enums import TurnInputModality
from alphaavatar.core.turn.schemas import TurnSnapshot

_SYSTEM_NOTICES = {
    "voice.transcription_unavailable": (
        "The speaker's words could not be transcribed.",
        "Briefly and naturally ask them to repeat what they said. Do not guess the words or the cause.",
    )
}


@dataclass(frozen=True, slots=True)
class TimedSystemNotice:
    segment_id: str | None
    at_ns: int | None
    part: ModelTextPart


def _segment_positions(snapshot: TurnSnapshot) -> dict[str, tuple[int, int]]:
    owned = set(snapshot.input_observation_ids)
    speech = [
        (observation.time_range.start.monotonic_ns, segment.segment_id)
        for event in snapshot.perception_events
        if (observation := event.observation) is not None
        and observation.kind == ObservationKind.SPEECH_SEGMENT
        and observation.observation_id in owned
        and (segment := observation.segment) is not None
    ]
    speech.sort(key=lambda item: item[0])
    return {
        segment_id: (position, start_ns)
        for position, (start_ns, segment_id) in enumerate(speech, 1)
    }


def _render_notice(
    snapshot: TurnSnapshot, *, current: bool, segments: tuple[tuple[str, int | None], ...]
) -> ModelTextPart:
    code = snapshot.system_notice_code
    assert code is not None

    fact, instruction = _SYSTEM_NOTICES.get(
        code, ("An input could not be understood.", "Briefly ask the user to try the input again.")
    )
    if snapshot.modality != TurnInputModality.SYSTEM:
        fact = "Part of this input could not be understood."
        instruction = (
            "Briefly acknowledge the missing part and respond to the recognized content. "
            "Ask only for the missing part if needed. Do not guess what was missed."
        )

    body = f"<fact>{escape(fact)}</fact>"
    for segment_id, position in segments:
        index = f' position="{position}"' if position is not None else ""
        body += f"<unavailable_speech segment_id={quoteattr(segment_id)}{index} />"
    if current:
        body += f"<instruction>{escape(instruction)}</instruction>"
    xml = f'<system_notice code={quoteattr(code)} current="{str(current).lower()}">{body}</system_notice>'
    return ModelTextPart(xml, kind=ModelTextPartKind.SYSTEM_NOTICE)


def render_system_notice(snapshot: TurnSnapshot, *, current: bool) -> ModelTextPart | None:
    if snapshot.system_notice_code is None:
        return None

    positions = _segment_positions(snapshot)
    segments = tuple(
        (segment_id, positions[segment_id][0] if segment_id in positions else None)
        for segment_id in snapshot.system_notice_segment_ids
    )
    return _render_notice(snapshot, current=current, segments=segments)


def render_timed_notices(snapshot: TurnSnapshot, *, current: bool) -> tuple[TimedSystemNotice, ...]:
    if snapshot.system_notice_code is None:
        return ()

    if snapshot.modality == TurnInputModality.SYSTEM or not snapshot.system_notice_segment_ids:
        part = render_system_notice(snapshot, current=current)
        assert part is not None
        return (TimedSystemNotice(None, None, part),)

    positions = _segment_positions(snapshot)
    segment_ids = snapshot.system_notice_segment_ids
    ordered = sorted(
        segment_ids, key=lambda segment_id: positions.get(segment_id, (len(positions) + 1, 0))
    )
    return tuple(
        TimedSystemNotice(
            segment_id,
            positions[segment_id][1] if segment_id in positions else None,
            _render_notice(
                snapshot,
                current=current,
                segments=(
                    (segment_id, positions[segment_id][0] if segment_id in positions else None),
                ),
            ),
        )
        for segment_id in ordered
    )
