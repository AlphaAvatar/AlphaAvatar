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

from alphaavatar.agents.router.enums import TurnTakingMode
from alphaavatar.agents.router.schemas import TurnTakingAudioEvidence, TurnTakingEvidence
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.env.schemas import PerceptionSegmentRef
from alphaavatar.core.media import AudioSegmentPayload, PayloadFormatUnavailable, TextPayload
from alphaavatar.core.media.enums import PayloadFormat, PayloadView
from alphaavatar.core.perception.enums import MediaModality, MediaSourceKind

from .schemas.state import InputWindow


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
                PayloadFormat.AUDIO_PCM16_BYTES, view=PayloadView.RAW, fallback_to_raw=False
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

    def mode(self, window: InputWindow) -> TurnTakingMode:
        devices = {actor.device_id for actor in window.actors if actor.device_id is not None}
        cameras = self._runtime.perception.get_source_states(
            modality=MediaModality.VIDEO, source_kind=MediaSourceKind.CAMERA
        )
        return (
            TurnTakingMode.AUDIO_VISUAL
            if any(source.available and source.device_id in devices for source in cameras)
            else TurnTakingMode.AUDIO_ONLY
        )

    def build(
        self, window: InputWindow, *, audio: tuple[TurnTakingAudioEvidence, ...] | None = None
    ) -> TurnTakingEvidence:
        return TurnTakingEvidence(
            input_id=window.input_id,
            revision=window.revision,
            turn_mode=self.mode(window),
            actors=window.actors,
            started_at=window.started_at,
            updated_at=window.updated_at,
            segments=tuple(window.segments),
            input_observation_ids=tuple(window.input_observation_ids),
            transcript=window.text or None,
            audio=audio
            if audio is not None
            else tuple(window.audio[s] for s in window.segments if s in window.audio),
            speech_active=bool(window.active_segments),
            has_perception_gap=window.has_perception_gap,
        )
