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
"""Doctor: diagnosis of the installation and a selected configuration, as plain data.

``diagnose`` runs the static checks, then a temporary diagnostic session of the configuration
on fixed samples (see ``session``).
"""

from .doctor import CHECKS, MAX_ROUNDS, ROUNDS, Diagnosis, diagnose, prepare
from .enums import CheckStatus, ScenarioOutcome
from .schemas import (
    Check,
    CheckSpec,
    Evidence,
    Metric,
    Report,
    RunnerResult,
    ScenarioResult,
    ServiceResult,
)

__all__ = [
    "CHECKS",
    "Check",
    "CheckSpec",
    "CheckStatus",
    "Diagnosis",
    "Evidence",
    "Metric",
    "Report",
    "RunnerResult",
    "ScenarioOutcome",
    "ScenarioResult",
    "ServiceResult",
    "diagnose",
    "MAX_ROUNDS",
    "ROUNDS",
    "prepare",
]
