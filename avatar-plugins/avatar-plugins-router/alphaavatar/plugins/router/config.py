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
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from alphaavatar.agents.interaction import InvocationPhrase

"""
Addressing Config
"""


class AddressingFusionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    conflict_margin: float = Field(default=0.1, ge=0.0, le=1.0)


class VisualAddressingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True

    toward_threshold: float = Field(default=0.72, ge=0.0, le=1.0)
    away_threshold: float = Field(default=0.35, ge=0.0, le=1.0)

    ema_alpha: float = Field(default=0.55, gt=0.0, le=1.0)
    min_samples: int = Field(default=2, gt=0)
    republish_interval_sec: float = Field(default=0.75, ge=0.0)

    publish_away_evidence: bool = True

    yaw_scale: float = Field(default=0.28, gt=0.0)
    roll_scale_deg: float = Field(default=25.0, gt=0.0)
    min_face_area_ratio: float = Field(default=0.01, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_thresholds(self) -> "VisualAddressingConfig":
        if self.away_threshold >= self.toward_threshold:
            raise ValueError("away_threshold must be smaller than toward_threshold")

        return self


class InvocationPhraseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phrase_id: str
    text: str
    boosting_score: float = Field(default=1.0, gt=0.0)
    trigger_threshold: float = Field(default=0.25, ge=0.0, le=1.0)

    @field_validator("phrase_id")
    @classmethod
    def validate_phrase_id(cls, value: str) -> str:
        if not value or any(character.isspace() or character in {"/", "@"} for character in value):
            raise ValueError("phrase_id cannot be empty or contain whitespace, '/' or '@'")
        return value

    def build(self) -> InvocationPhrase:
        return InvocationPhrase(
            phrase_id=self.phrase_id,
            text=self.text,
            boosting_score=self.boosting_score,
            trigger_threshold=self.trigger_threshold,
        )


class InvocationAddressingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    provider: str = "sherpa_onnx"

    evidence_confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    early_window_sec: float = Field(default=2.0, ge=0.0)
    late_confidence_scale: float = Field(default=0.6, ge=0.0, le=1.0)

    chunk_duration_ms: int = Field(default=160, ge=20)
    max_pending_chunks: int = Field(default=8, gt=0)
    tail_padding_sec: float = Field(default=0.66, ge=0.0)

    phrases: tuple[InvocationPhraseConfig, ...] = ()

    @model_validator(mode="after")
    def validate_phrases(self) -> "InvocationAddressingConfig":
        if self.enabled and not self.phrases:
            raise ValueError("Invocation addressing requires at least one phrase")

        phrase_ids = [phrase.phrase_id for phrase in self.phrases]
        if len(phrase_ids) != len(set(phrase_ids)):
            raise ValueError("Invocation phrase_id values must be unique")

        return self


class AddressingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    addressing_wait_sec: float = Field(default=0.5, gt=0.0)

    visual: VisualAddressingConfig = Field(default_factory=VisualAddressingConfig)
    invocation: InvocationAddressingConfig = Field(default_factory=InvocationAddressingConfig)
    fusion: AddressingFusionConfig = Field(default_factory=AddressingFusionConfig)


"""
TurnTaking Config
"""


class TurnTakingModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "smart_turn_v3"


class TurnTakingPolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commit_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    max_hold_sec: float = Field(default=1.5, gt=0.0)
    respond_to_group: bool = False


class TurnTakingInterruptionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    audio_only_speech_start: bool = True


class TurnTakingOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    transcript_wait_sec: float = Field(default=0.75, ge=0.0)
    unsegmented_alignment_sec: float = Field(default=0.75, gt=0.0)

    model: TurnTakingModelConfig = Field(default_factory=TurnTakingModelConfig)
    policy: TurnTakingPolicyConfig = Field(default_factory=TurnTakingPolicyConfig)
    interruption: TurnTakingInterruptionConfig = Field(default_factory=TurnTakingInterruptionConfig)


"""
Config Class
"""


class AudioActivityOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    pre_roll_sec: float = Field(default=0.3, ge=0.0)
    max_buffer_sec: float = Field(default=2.0, gt=0.0)

    @model_validator(mode="after")
    def validate_buffer(self) -> "AudioActivityOptions":
        if self.max_buffer_sec < self.pre_roll_sec:
            raise ValueError("max_buffer_sec cannot be smaller than pre_roll_sec")
        return self


class DefaultRouterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audio_activity: AudioActivityOptions = Field(default_factory=AudioActivityOptions)
    addressing: AddressingConfig = Field(default_factory=AddressingConfig)
    turn_taking: TurnTakingOptions = Field(default_factory=TurnTakingOptions)
