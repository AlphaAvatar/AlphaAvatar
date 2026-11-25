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
from alphaavatar.core.turn.schemas import TurnNotice, TurnSnapshot

_UNCERTAINTY = frozenset(("router.speech_completion_uncertain", "router.addressing_uncertain"))
_SYSTEM_NOTICES = {
    "voice.transcription_unavailable": (
        "The speaker's words could not be transcribed.",
        "Briefly and naturally ask them to repeat what they said. Do not guess the words or the cause.",
    ),
    "router.speech_completion_uncertain": (
        "The system could not determine whether the speaker had finished this turn.",
        "If the intent is clear, respond naturally; otherwise briefly ask whether the speaker "
        "would like to continue. Do not assume the speech was incomplete.",
    ),
    "router.addressing_uncertain": (
        "The system could not determine whether this speech was addressed to the Avatar.",
        "Do not assume the speech was addressed to you. If the intended addressee is unclear "
        "from the content, briefly ask whether the speaker was speaking to you.",
    ),
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
    notice: TurnNotice,
    *,
    current: bool,
    partial: bool,
    segments: tuple[tuple[str, int | None], ...],
) -> ModelTextPart:
    code = notice.code

    fact, instruction = _SYSTEM_NOTICES.get(
        code, ("An input could not be understood.", "Briefly ask the user to try the input again.")
    )
    if partial:
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


def render_timed_notices(snapshot: TurnSnapshot, *, current: bool) -> tuple[TimedSystemNotice, ...]:
    if not snapshot.system_notices:
        return ()

    positions = _segment_positions(snapshot)
    found = []
    for notice in snapshot.system_notices:
        uncertainty = notice.code in _UNCERTAINTY
        segments = (
            tuple(
                (segment_id, positions[segment_id][0] if segment_id in positions else None)
                for segment_id in notice.segment_ids
            )
            if not uncertainty
            else ()
        )
        partial = not uncertainty and snapshot.modality != TurnInputModality.SYSTEM
        if uncertainty or snapshot.modality == TurnInputModality.SYSTEM or not segments:
            found.append(
                TimedSystemNotice(
                    None,
                    None,
                    _render_notice(notice, current=current, partial=partial, segments=segments),
                )
            )
            continue

        ordered = sorted(segments, key=lambda item: positions.get(item[0], (len(positions) + 1, 0)))
        for segment_id, position in ordered:
            found.append(
                TimedSystemNotice(
                    segment_id,
                    positions[segment_id][1] if segment_id in positions else None,
                    _render_notice(
                        notice, current=current, partial=partial, segments=((segment_id, position),)
                    ),
                )
            )
    return tuple(found)
