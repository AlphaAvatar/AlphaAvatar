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

from alphaavatar.agents.router.enums import (
    AddressingMode,
    AssessmentLabel,
    InteractionEntityKind,
    TurnTakingAction,
    TurnTakingMode,
)
from alphaavatar.agents.router.schemas import (
    InteractionAddressing,
    InteractionAddressingEvidence,
    InteractionEntityRef,
    TurnTakingAssessment,
    TurnTakingDecision,
    TurnTakingEvidence,
)
from alphaavatar.core.turn.schemas import TurnNotice


@dataclass(frozen=True, slots=True)
class TurnTakingPolicyResult:
    decision: TurnTakingDecision
    addressing: InteractionAddressing | None = None


class TurnTakingPolicy:
    def __init__(
        self,
        *,
        interruption_enabled: bool = True,
        audio_only_speech_start_interrupt: bool = True,
        respond_to_group: bool = False,
    ) -> None:
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
        evidence: TurnTakingEvidence, addressing_ids: tuple[str, ...] = ()
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
        notices: tuple[TurnNotice, ...] = (),
    ) -> TurnTakingPolicyResult:
        addressing = None
        if addressees:
            addressing = InteractionAddressing(
                input_id=evidence.input_id,
                revision=evidence.revision,
                actors=evidence.actors,
                addressees=addressees,
                addressing_mode=addressing_mode,
                confidence=(confidence if addressing_confidence is None else addressing_confidence),
                evidence_observation_ids=self._evidence_ids(evidence, addressing_evidence_ids),
            )

        return TurnTakingPolicyResult(
            addressing=addressing,
            decision=TurnTakingDecision(
                input_id=evidence.input_id,
                revision=evidence.revision,
                turn_mode=evidence.turn_mode,
                action=action,
                confidence=confidence,
                actors=evidence.actors,
                addressees=addressees,
                input_observation_ids=evidence.input_observation_ids,
                reason=reason,
                system_notices=notices,
            ),
        )

    def decide(
        self,
        *,
        evidence: TurnTakingEvidence,
        assessment: TurnTakingAssessment,
        completion_expired: bool = False,
        addressing_expired: bool = False,
    ) -> TurnTakingPolicyResult:
        completion, addressing = assessment.speech_completion, assessment.addressing
        addressees, mode = assessment.addressees, assessment.addressing_mode
        notices: tuple[TurnNotice, ...] = ()

        # A deadline settles uncertainty; it never reverses a clear model conclusion.
        if completion == AssessmentLabel.NEGATIVE:
            action, reason = TurnTakingAction.HOLD, "speech_incomplete"
        elif addressing == AssessmentLabel.NEGATIVE:
            action, reason = TurnTakingAction.PASSIVE, "addressed_to_other"
        elif completion == AssessmentLabel.UNKNOWN and not completion_expired:
            action, reason = TurnTakingAction.HOLD, "speech_completion_unknown"
        elif addressing == AssessmentLabel.UNKNOWN and not addressing_expired:
            action, reason = TurnTakingAction.HOLD, "addressing_unknown"
        elif addressing == AssessmentLabel.POSITIVE and not (
            self._addresses_avatar(addressees)
            or mode == AddressingMode.GROUP
            and self._respond_to_group
        ):
            action, reason = TurnTakingAction.PASSIVE, "addressed_to_other"
        else:
            action = TurnTakingAction.COMMIT
            notices = tuple(
                TurnNotice(code)
                for label, code in (
                    (completion, "router.speech_completion_uncertain"),
                    (addressing, "router.addressing_uncertain"),
                )
                if label == AssessmentLabel.UNKNOWN
            )
            reason = "uncertainty_timeout" if notices else "speech_complete"

        return self._result(
            evidence=evidence,
            action=action,
            confidence=0.0 if notices else self._confidence(assessment),
            addressees=addressees,
            addressing_mode=mode,
            addressing_confidence=assessment.addressing_confidence,
            addressing_evidence_ids=assessment.addressing_evidence_observation_ids,
            reason=reason,
            notices=notices,
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
