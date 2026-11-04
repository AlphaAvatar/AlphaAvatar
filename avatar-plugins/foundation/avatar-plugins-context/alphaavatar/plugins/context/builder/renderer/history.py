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
from alphaavatar.core.turn.enums import TurnInputModality
from alphaavatar.core.turn.schemas import TurnSnapshot

from .notice import render_system_notice


def render_history_seed(snapshot: TurnSnapshot, context_id: str) -> ModelInputMessage:
    parts = []
    if snapshot.text is not None:
        parts.append(ModelTextPart(escape(snapshot.text)))
    elif snapshot.modality != TurnInputModality.SYSTEM or snapshot.system_notice_code is None:
        parts.append(
            ModelTextPart(
                '<historical_media omitted="true" current="false">'
                "Visual input belongs to this earlier turn; do not infer its contents from this placeholder."
                "</historical_media>"
            )
        )
    if notice := render_system_notice(snapshot, current=False):
        parts.append(notice)
    return ModelInputMessage(
        id=snapshot.input_id,
        role=ModelRole.USER,
        parts=tuple(parts),
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
