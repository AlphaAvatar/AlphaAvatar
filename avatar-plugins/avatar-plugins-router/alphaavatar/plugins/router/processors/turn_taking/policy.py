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

from dataclasses import dataclass

from alphaavatar.agents.router import (
    AddressingMode,
    InteractionAddressing,
    InteractionAddressingEvidence,
    InteractionEntityKind,
    InteractionEntityRef,
    TurnTakingAction,
    TurnTakingAssessment,
    TurnTakingDecision,
    TurnTakingEvidence,
    TurnTakingMode,
)


@dataclass(frozen=True, slots=True)
class TurnTakingPolicyResult:
    decision: TurnTakingDecision
    addressing: InteractionAddressing | None = None


class TurnTakingPolicy:
    def __init__(
        self,
        *,
        commit_threshold: float = 0.5,
        interruption_enabled: bool = True,
        audio_only_speech_start_interrupt: bool = True,
        respond_to_group: bool = False,
    ) -> None:
        if not 0.0 <= commit_threshold <= 1.0:
            raise ValueError("commit_threshold must be between 0 and 1")

        self._commit_threshold = commit_threshold
        self._interruption_enabled = interruption_enabled
        self._audio_only_speech_start_interrupt = audio_only_speech_start_interrupt
        self._respond_to_group = respond_to_group

    @staticmethod
    def _avatar() -> InteractionEntityRef:
        return InteractionEntityRef(kind=InteractionEntityKind.AVATAR)

    @staticmethod
    def _addresses_avatar(addressees: tuple[InteractionEntityRef, ...]) -> bool:
        return any(entity.kind == InteractionEntityKind.AVATAR for entity in addressees)

    @staticmethod
    def _confidence(assessment: TurnTakingAssessment) -> float:
        return (
            assessment.confidence
            if assessment.addressing_confidence is None
            else min(assessment.confidence, assessment.addressing_confidence)
        )

    @staticmethod
    def _evidence_ids(
        evidence: TurnTakingEvidence,
        addressing_ids: tuple[str, ...] = (),
    ) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*evidence.input_observation_ids, *addressing_ids)))

    def _result(
        self,
        *,
        evidence: TurnTakingEvidence,
        action: TurnTakingAction,
        confidence: float,
        addressees: tuple[InteractionEntityRef, ...] = (),
        addressing_mode: AddressingMode = AddressingMode.UNKNOWN,
        addressing_confidence: float | None = None,
        addressing_evidence_ids: tuple[str, ...] = (),
        reason: str | None = None,
    ) -> TurnTakingPolicyResult:
        addressing = None
        if addressees:
            addressing = InteractionAddressing(
                turn_candidate_id=evidence.turn_candidate_id,
                candidate_revision=evidence.candidate_revision,
                speaker=evidence.speaker,
                addressees=addressees,
                addressing_mode=addressing_mode,
                confidence=(confidence if addressing_confidence is None else addressing_confidence),
                evidence_observation_ids=self._evidence_ids(
                    evidence,
                    addressing_evidence_ids,
                ),
            )

        return TurnTakingPolicyResult(
            addressing=addressing,
            decision=TurnTakingDecision(
                turn_candidate_id=evidence.turn_candidate_id,
                candidate_revision=evidence.candidate_revision,
                turn_mode=evidence.turn_mode,
                action=action,
                confidence=confidence,
                actor=evidence.speaker,
                addressees=addressees,
                input_observation_ids=evidence.input_observation_ids,
                reason=reason,
            ),
        )

    def decide(
        self,
        *,
        evidence: TurnTakingEvidence,
        assessment: TurnTakingAssessment,
    ) -> TurnTakingPolicyResult:
        end_probability = assessment.end_of_turn_probability or 0.0
        addressees = assessment.addressees
        addressing_mode = assessment.addressing_mode

        if evidence.turn_mode == TurnTakingMode.AUDIO_ONLY and not addressees:
            addressees = (self._avatar(),)
            addressing_mode = AddressingMode.DIRECT

        if end_probability < self._commit_threshold:
            action = TurnTakingAction.HOLD
            reason = assessment.reason or "endpoint_incomplete"
        elif evidence.turn_mode == TurnTakingMode.AUDIO_VISUAL and (
            not addressees or addressing_mode == AddressingMode.UNKNOWN
        ):
            action = TurnTakingAction.HOLD
            reason = "addressing_unknown"
        elif self._addresses_avatar(addressees):
            action = TurnTakingAction.COMMIT
            reason = assessment.reason
        elif addressing_mode == AddressingMode.GROUP and self._respond_to_group:
            action = TurnTakingAction.COMMIT
            reason = "group_addressing"
        else:
            action = TurnTakingAction.PASSIVE
            reason = "addressed_to_other"

        confidence = self._confidence(assessment)
        return self._result(
            evidence=evidence,
            action=action,
            confidence=confidence,
            addressees=addressees,
            addressing_mode=addressing_mode,
            addressing_confidence=assessment.addressing_confidence,
            addressing_evidence_ids=assessment.addressing_evidence_observation_ids,
            reason=reason,
        )

    def decide_interruption(
        self,
        *,
        evidence: TurnTakingEvidence,
        addressing: InteractionAddressingEvidence | None = None,
    ) -> TurnTakingPolicyResult | None:
        if not self._interruption_enabled or not evidence.speech_active:
            return None

        if evidence.turn_mode == TurnTakingMode.AUDIO_ONLY:
            if not self._audio_only_speech_start_interrupt:
                return None

            addressees = (self._avatar(),)
            addressing_mode = AddressingMode.DIRECT
            confidence = 1.0
            addressing_ids: tuple[str, ...] = ()
        elif (
            evidence.turn_mode == TurnTakingMode.AUDIO_VISUAL
            and addressing is not None
            and self._addresses_avatar(addressing.addressees)
        ):
            addressees = addressing.addressees
            addressing_mode = addressing.addressing_mode
            confidence = addressing.confidence
            addressing_ids = addressing.evidence_observation_ids
        else:
            return None

        return self._result(
            evidence=evidence,
            action=TurnTakingAction.INTERRUPT,
            confidence=confidence,
            addressees=addressees,
            addressing_mode=addressing_mode,
            addressing_confidence=confidence,
            addressing_evidence_ids=addressing_ids,
            reason="avatar_directed_speech_started",
        )

    def resolve_timeout(
        self,
        *,
        evidence: TurnTakingEvidence,
        assessment: TurnTakingAssessment | None,
        reason: str,
    ) -> TurnTakingPolicyResult:
        addressing_ids = (
            assessment.addressing_evidence_observation_ids if assessment is not None else ()
        )

        if assessment is not None and assessment.addressees:
            addressees = assessment.addressees
            addressing_mode = assessment.addressing_mode

            if self._addresses_avatar(addressees):
                action = TurnTakingAction.COMMIT
            elif addressing_mode == AddressingMode.GROUP and self._respond_to_group:
                action = TurnTakingAction.COMMIT
            else:
                action = TurnTakingAction.PASSIVE

        elif evidence.turn_mode == TurnTakingMode.AUDIO_ONLY:
            addressees = (self._avatar(),)
            addressing_mode = AddressingMode.DIRECT
            action = TurnTakingAction.COMMIT

        else:
            addressees = ()
            addressing_mode = AddressingMode.UNKNOWN
            action = TurnTakingAction.PASSIVE

        return self._result(
            evidence=evidence,
            action=action,
            confidence=0.0,
            addressees=addressees,
            addressing_mode=addressing_mode,
            addressing_confidence=(
                assessment.addressing_confidence if assessment is not None else None
            ),
            addressing_evidence_ids=addressing_ids,
            reason=reason,
        )
