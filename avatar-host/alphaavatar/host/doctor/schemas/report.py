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

from dataclasses import asdict, dataclass
from typing import Any

from ..enums import CheckStatus
from .session import Metric, RunnerResult, ScenarioResult


@dataclass(frozen=True, slots=True)
class CheckSpec:
    id: str
    title: str
    needs_configuration: bool = False
    in_session: bool = False  # Runs in the diagnostic session.


@dataclass(frozen=True, slots=True)
class Check:
    id: str
    status: CheckStatus
    summary: str
    details: tuple[str, ...] = ()
    action: str | None = None  # The next step, for anything but a pass.
    runners: tuple[RunnerResult, ...] = ()
    scenarios: tuple[ScenarioResult, ...] = ()
    metrics: tuple[Metric, ...] = ()


@dataclass(frozen=True, slots=True)
class Report:
    checks: tuple[Check, ...]

    @property
    def status(self) -> CheckStatus:
        """FAIL if any check failed, else WARN if any warned; skipped checks never pass."""
        statuses = {check.status for check in self.checks}
        for status in (CheckStatus.FAIL, CheckStatus.WARN):
            if status in statuses:
                return status
        return CheckStatus.PASS

    @property
    def exit_code(self) -> int:
        """1 when a check failed; 0 otherwise, warnings and unverified checks included."""
        return 1 if self.status == CheckStatus.FAIL else 0

    def counts(self) -> dict[CheckStatus, int]:
        return {
            status: sum(check.status == status for check in self.checks) for status in CheckStatus
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "counts": self.counts(),
            "checks": [asdict(check) for check in self.checks],
        }
