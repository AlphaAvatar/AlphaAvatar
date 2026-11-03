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


@dataclass(frozen=True, slots=True)
class CheckSpec:
    id: str
    title: str
    needs_configuration: bool = False
    needs_runtime: bool = False  # Run with --runtime only.


@dataclass(frozen=True, slots=True)
class RunnerResult:
    """One selected runner in a runtime check, with what its local run measured."""

    method: str
    status: CheckStatus
    summary: str
    details: tuple[str, ...] = ()
    action: str | None = None
    model: str | None = None
    # From runner start to ready, as the runtime's startup snapshot records it.
    initialize_seconds: float | None = None
    # Each request through the executor: the first, then the later ones.
    inference_seconds: tuple[float, ...] = ()
    audio_seconds: float | None = None
    # The later requests' median over the audio one request carries.
    real_time_factor: float | None = None
    device: str | None = None
    output: str | None = None  # What the probe found in the last answer.


@dataclass(frozen=True, slots=True)
class Check:
    id: str
    status: CheckStatus
    summary: str
    details: tuple[str, ...] = ()
    action: str | None = None  # The next step, for anything but a pass.
    runners: tuple[RunnerResult, ...] = ()


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
