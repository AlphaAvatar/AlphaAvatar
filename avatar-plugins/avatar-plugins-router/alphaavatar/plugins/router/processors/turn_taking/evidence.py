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

from alphaavatar.agents.router import (
    TurnTakingAudioEvidence,
    TurnTakingEvidence,
    TurnTakingMode,
)
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.core.env import EnvObservation, PerceptionSegmentRef
from alphaavatar.core.media import (
    AudioSegmentPayload,
    PayloadFormat,
    PayloadFormatUnavailable,
    PayloadView,
    TextPayload,
)
from alphaavatar.core.perception import MediaModality, MediaSourceKind

from .schemas.state import TurnCandidate


class TurnEvidenceBuilder:
    def __init__(self, runtime: AvatarRuntime) -> None:
        self._runtime = runtime

    @staticmethod
    def require_segment(observation: EnvObservation) -> PerceptionSegmentRef:
        if observation.segment is None:
            raise RuntimeError(f"{observation.kind.value} observation has no segment reference")
        return observation.segment

    @staticmethod
    def text(observation: EnvObservation) -> str | None:
        payload = observation.payload
        if not isinstance(payload, TextPayload):
            return None
        return payload.text.strip() or None

    @staticmethod
    def audio(observation: EnvObservation) -> TurnTakingAudioEvidence | None:
        payload = observation.payload
        if observation.segment is None or not isinstance(payload, AudioSegmentPayload):
            return None

        try:
            pcm16_bytes = payload.get(
                PayloadFormat.AUDIO_PCM16_BYTES,
                view=PayloadView.RAW,
                fallback_to_raw=False,
            )
        except PayloadFormatUnavailable:
            return None

        if not isinstance(pcm16_bytes, bytes):
            raise TypeError("Speech segment PCM representation must be bytes")

        return TurnTakingAudioEvidence(
            segment=observation.segment,
            time_range=observation.time_range,
            pcm16_bytes=pcm16_bytes,
            sample_rate=payload.sample_rate,
            num_channels=payload.num_channels,
            samples_per_channel=payload.samples_per_channel,
        )

    def mode(self, candidate: TurnCandidate) -> TurnTakingMode:
        participant_id = candidate.speaker.transport_participant_id
        if participant_id is None:
            return TurnTakingMode.AUDIO_ONLY

        cameras = self._runtime.perception.get_source_states(
            modality=MediaModality.VIDEO,
            source_kind=MediaSourceKind.CAMERA,
        )
        return (
            TurnTakingMode.AUDIO_VISUAL
            if any(
                source.available and source.transport_participant_id == participant_id
                for source in cameras
            )
            else TurnTakingMode.AUDIO_ONLY
        )

    def build(self, candidate: TurnCandidate) -> TurnTakingEvidence:
        return TurnTakingEvidence(
            turn_candidate_id=candidate.turn_candidate_id,
            candidate_revision=candidate.revision,
            turn_mode=self.mode(candidate),
            speaker=candidate.speaker,
            started_at=candidate.started_at,
            updated_at=candidate.updated_at,
            segments=tuple(candidate.segments),
            input_observation_ids=tuple(candidate.input_observation_ids),
            transcript=candidate.text or None,
            audio=tuple(
                candidate.audio[segment]
                for segment in candidate.segments
                if segment in candidate.audio
            ),
            speech_active=bool(candidate.active_segments),
            has_perception_gap=candidate.has_perception_gap,
        )
