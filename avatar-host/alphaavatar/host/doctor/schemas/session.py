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

from dataclasses import dataclass, field

from ..enums import CheckStatus, ScenarioOutcome


@dataclass(frozen=True, slots=True)
class Metric:
    """One measured interval or rate, between two named events on the session clock.

    ``value`` is None when an event was not observed; ``values`` holds each sample.
    """

    name: str
    value: float | None
    unit: str
    start: str
    end: str
    boundary: str
    samples: int = 1
    values: tuple[float, ...] = ()
    note: str | None = None


@dataclass(frozen=True, slots=True)
class Evidence:
    """One observed step, in observation order; times are relative to the response start."""

    at_ms: float
    stage: str
    source: str  # input, trace, output or log
    detail: dict[str, str | int | float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    """One modality scenario run on the original or a degraded configuration."""

    name: str
    outcome: ScenarioOutcome
    summary: str
    configuration: str  # "original", or the degradation applied
    blocked_stage: str | None = None
    cause: str | None = None  # What stopped it, as its producer names it
    details: tuple[str, ...] = ()
    task: str | None = None
    transcript: str | None = None  # Bounded and redacted, as the report boundary leaves it.
    answer: str | None = None
    reached: tuple[str, ...] = ()  # The stages observed, in chain order
    # The Turn's first model request: identity tokens, and what it carries of the Turn.
    request: dict[str, str | int | bool] = field(default_factory=dict)
    # Each output of the Turn's run: completed, failed, interrupted, timed_out or not_ended.
    outputs: tuple[dict[str, str | float | None], ...] = ()
    metrics: tuple[Metric, ...] = ()
    segments: tuple[Metric, ...] = ()
    # Frames Context selected and frames the request carries; published: one of Doctor's.
    frames: tuple[dict[str, str | int | float | bool], ...] = ()
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, slots=True)
class RunnerResult:
    """One planned runner as the diagnostic session's runtime started it."""

    method: str
    status: CheckStatus
    summary: str
    details: tuple[str, ...] = ()
    startup_seconds: float | None = None
    configuration: str = "original"


@dataclass(frozen=True, slots=True)
class ServiceResult:
    """One external service the configuration names, and how far the diagnosis got with it.

    ``reached`` and ``passed`` are None when nothing Doctor ran could show either.
    """

    name: str
    authorized: bool
    reached: bool | None = None
    passed: bool | None = None
    note: str | None = None
