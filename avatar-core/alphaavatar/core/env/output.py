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

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .schemas.metadata import EMPTY_METADATA, OutputMetadata, freeze_metadata

if TYPE_CHECKING:
    from alphaavatar.core.media import AudioFrame
    from alphaavatar.core.output.enums import OutputKind, OutputLane
    from alphaavatar.core.output.schemas import (
        OutputControl,
        OutputPlayback,
        OutputScope,
        OutputSource,
        OutputStatusDecision,
        OutputTextAudioAlignment,
        OutputTextChunk,
        OutputTranscriptChunk,
    )

EnvOutputPayload = (
    AudioFrame
    | OutputTextChunk
    | OutputTranscriptChunk
    | OutputTextAudioAlignment
    | OutputPlayback
    | OutputStatusDecision
    | OutputControl
)


@dataclass(frozen=True, slots=True, kw_only=True)
class EnvOutput:
    """Validated output content, not an observation or a command to mutate runtime state.

    Schema imports are delayed until construction: importing EnvObservation must not
    initialize OutputRuntime through core.output's public package exports.
    """

    kind: OutputKind
    lane: OutputLane
    scope: OutputScope | None
    source: OutputSource
    payload: EnvOutputPayload
    output_id: str | None = None
    presentation: OutputStatusDecision | None = None
    metadata: OutputMetadata | Mapping[str, object] = field(default_factory=lambda: EMPTY_METADATA)

    def __post_init__(self) -> None:
        from alphaavatar.core.media import AudioFrame
        from alphaavatar.core.media.audio import AudioSampleFormat
        from alphaavatar.core.output.enums import (
            OutputAudience,
            OutputControlType,
            OutputKind,
            OutputLane,
        )
        from alphaavatar.core.output.schemas import (
            OutputControl,
            OutputPlayback,
            OutputScope,
            OutputSource,
            OutputStatusDecision,
            OutputTextAudioAlignment,
            OutputTextChunk,
            OutputTranscriptChunk,
        )
        from alphaavatar.core.output.schemas.validation import identifier

        if type(self.kind) is not OutputKind or type(self.lane) is not OutputLane:
            raise TypeError("EnvOutput requires typed kind and lane")
        if type(self.source) is not OutputSource:
            raise TypeError("EnvOutput requires typed provenance")
        if self.scope is not None and type(self.scope) is not OutputScope:
            raise TypeError("EnvOutput requires typed scope")
        if self.scope is not None:
            identifier(self.scope.context_id, "context_id")
            identifier(self.scope.turn_id, "turn_id", optional=True)
            identifier(self.scope.run_id, "run_id", optional=True)
            if self.scope.run_id is not None and self.scope.turn_id is None:
                raise ValueError("Run-scoped output requires its turn")

        payload_types = {
            OutputKind.TEXT_CHUNK: OutputTextChunk,
            OutputKind.AUDIO_FRAME: AudioFrame,
            OutputKind.ALIGNMENT: OutputTextAudioAlignment,
            OutputKind.PLAYBACK: OutputPlayback,
            OutputKind.TRANSCRIPT_CHUNK: OutputTranscriptChunk,
            OutputKind.STATUS: OutputStatusDecision,
            OutputKind.CONTROL: OutputControl,
        }
        if type(self.payload) is not payload_types[self.kind]:
            raise TypeError("Output kind does not match its payload")
        if self.kind == OutputKind.STATUS:
            if (
                self.lane != OutputLane.STATUS
                or self.output_id is not None
                or self.scope != self.payload.scope
            ):
                raise ValueError("Status envelope must match its decision scope")
        elif self.kind == OutputKind.CONTROL and self.payload.type == OutputControlType.INTERRUPT:
            if self.output_id is not None or self.scope is not None:
                raise ValueError("Interrupt identities belong exclusively to its exact target set")
        else:
            identifier(self.output_id, "output_id")
            if self.lane == OutputLane.STATUS or self.scope is None or self.scope.turn_id is None:
                raise ValueError("Content requires a turn-scoped content lane")
        if self.presentation is not None:
            decision = self.presentation
            if type(decision) is not OutputStatusDecision:
                raise TypeError("Expected OutputStatusDecision")
            if (
                self.kind != OutputKind.TEXT_CHUNK
                or self.lane != OutputLane.TRANSIENT
                or decision.audience != OutputAudience.USER
                or not decision.narration_key
                or self.scope != decision.scope
            ):
                raise ValueError("Narration must carry its own user presentation decision")
        if self.kind == OutputKind.AUDIO_FRAME:
            frame = self.payload
            if any(
                type(value) is not int or value <= 0
                for value in (frame.sample_rate, frame.num_channels, frame.samples_per_channel)
            ):
                raise ValueError("Audio dimensions must be positive integers")
            if type(frame.sample_format) is not AudioSampleFormat or type(frame.data) is not bytes:
                raise TypeError("Audio requires a typed sample format and immutable PCM bytes")
            if len(frame.data) != frame.expected_nbytes:
                raise ValueError("Audio byte length does not match shape")

        object.__setattr__(self, "metadata", freeze_metadata(self.metadata))
