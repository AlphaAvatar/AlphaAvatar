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
from dataclasses import replace
from types import MappingProxyType
from xml.sax.saxutils import escape

from alphaavatar.agents.avatar.provider.enums import ModelRole
from alphaavatar.agents.avatar.provider.schemas import (
    ModelAudioPart,
    ModelImagePart,
    ModelInputMessage,
    ModelTextPart,
)
from alphaavatar.core.env.enums import ObservationKind
from alphaavatar.core.media import TextPayload
from alphaavatar.core.turn.enums import TurnInputModality
from alphaavatar.core.turn.schemas import TurnSnapshot

from ..notice import render_system_notice, render_timed_notices


def _history_parts(snapshot: TurnSnapshot) -> tuple[ModelTextPart, ...]:
    if snapshot.text is not None:
        parts = (ModelTextPart(escape(snapshot.text)),)
    elif snapshot.modality == TurnInputModality.SYSTEM and snapshot.system_notice_code is not None:
        parts = ()
    else:
        parts = (
            ModelTextPart(
                '<historical_media omitted="true" current="false">'
                "Visual input belongs to this earlier turn; do not infer its contents from this placeholder."
                "</historical_media>"
            ),
        )

    if snapshot.text is not None and snapshot.system_notice_segment_ids:
        owned = set(snapshot.input_observation_ids)
        inputs = sorted(
            (observation.time_range.start.monotonic_ns, event.sequence, observation.payload.text)
            for event in snapshot.perception_events
            if (observation := event.observation) is not None
            and observation.observation_id in owned
            and observation.kind in (ObservationKind.TEXT_INPUT, ObservationKind.TRANSCRIPT_SEGMENT)
            and isinstance(observation.payload, TextPayload)
            and observation.payload.text.strip()
        )
        notices = render_timed_notices(snapshot, current=False)
        ordered = [
            (at_ns, notice.part) for notice in notices if (at_ns := notice.at_ns) is not None
        ]
        # Preserve committed text if the snapshot no longer has every timed observation.
        if (
            len(ordered) == len(notices)
            and " ".join(text for _, _, text in inputs) == snapshot.text
        ):
            ordered.extend((at_ns, ModelTextPart(escape(text))) for at_ns, _, text in inputs)
            return tuple(part for _, part in sorted(ordered, key=lambda item: item[0]))

    if notice := render_system_notice(snapshot, current=False):
        return (*parts, notice)
    return parts


def render_history_seed(snapshot: TurnSnapshot, context_id: str) -> ModelInputMessage:
    return ModelInputMessage(
        id=snapshot.input_id,
        role=ModelRole.USER,
        parts=_history_parts(snapshot),
        created_at=snapshot.committed_at.unix_seconds,
        metadata=MappingProxyType(
            {
                "context_id": context_id,
                "turn_id": snapshot.turn_id,
                "input_modality": snapshot.modality.value,
            }
        ),
    )


def _historical_media_placeholder(*, image_count: int, audio_count: int) -> ModelTextPart:
    return ModelTextPart(
        '<historical_media omitted="true" current="false" '
        f'image_count="{image_count}" audio_count="{audio_count}">'
        "This media belonged to an earlier message and is not current input."
        "</historical_media>"
    )


def compact_historical_message(message: ModelInputMessage) -> ModelInputMessage:
    parts = []
    image_count = audio_count = 0
    for part in message.parts:
        if isinstance(part, ModelImagePart):
            image_count += 1
        elif isinstance(part, ModelAudioPart):
            audio_count += 1
        else:
            parts.append(part)
    if image_count or audio_count:
        parts.append(
            _historical_media_placeholder(image_count=image_count, audio_count=audio_count)
        )
    return replace(message, parts=tuple(parts))
