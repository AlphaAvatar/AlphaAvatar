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

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..enum import TurnTakingMode
from ..schema import TurnTakingAssessment, TurnTakingEvidence


@dataclass(frozen=True, slots=True)
class TurnTakingModelCapabilities:
    modes: frozenset[TurnTakingMode]
    uses_audio: bool = False
    uses_transcript: bool = False
    uses_annotations: bool = False

    def supports(self, mode: TurnTakingMode) -> bool:
        return mode in self.modes


class TurnTakingModelBase(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def capabilities(self) -> TurnTakingModelCapabilities: ...

    @abstractmethod
    async def assess(
        self,
        evidence: TurnTakingEvidence,
    ) -> TurnTakingAssessment:
        """
        Assess one immutable candidate revision.

        Implementations must not mutate evidence or trigger interaction
        side effects.
        """
