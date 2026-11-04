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
"""Doctor command: arguments and presentation; the checks live in ``alphaavatar.host.doctor``.

Text and JSON show the same report, already through the configuration output boundary.
Styles only decorate text on a terminal. Exit codes: 0 nothing failed, 1 a check failed,
2 invalid arguments, 130 interrupted (the report still shows what ran).
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict

from alphaavatar.host.doctor import CheckStatus, ScenarioOutcome
from alphaavatar.host.log.format import BOLD, DIM, GREEN, RED, RESET, YELLOW, use_color

_STYLES = {
    CheckStatus.PASS: GREEN,
    CheckStatus.WARN: YELLOW,
    CheckStatus.FAIL: RED,
    CheckStatus.SKIP: DIM,
}
_OUTCOMES = {
    ScenarioOutcome.PASSED: GREEN,
    ScenarioOutcome.FAILED: RED,
    ScenarioOutcome.INTERRUPTED: YELLOW,
}
# The figures table: one row each, a column per measured scenario, in milliseconds.
_FIGURES = (
    "first_text",
    "first_audio_frame",
    "text_complete",
    "audio_last_frame",
    "response_final",
    "last_required_input",
    "vad_close",
    "stt_final",
    "turn_cutoff",
    "context_ready_wait",
    "cutoff_to_model_request",
    "model_first_event",
    "model_first_text_delta",
    "first_displayable_text",
    "tts_request_to_first_pcm",
    "tts_request_to_first_audio_frame",
    "selected_frame_age",
    "last_selected_frame_to_cutoff",
)
# Text groups only; JSON keeps the flat list and the stable check IDs.
GROUPS = {
    "environment": ("system.platform", "python.version", "packages.alphaavatar"),
    "configuration": ("config.load", "config.runners", "packages.capabilities"),
    "directories": ("paths.home", "paths.cache", "paths.workspace"),
    "session": (
        "session.start",
        "models.runners",
        "services.external",
        "session.scenarios",
        "session.cleanup",
    ),
    "not verified": ("devices.media",),
}


def doctor(target: str | None, overrides: Sequence[str], *, as_json: bool, listing: bool) -> int:
    from alphaavatar.host.doctor import CHECKS

    color = use_color("auto", sys.stdout)

    def paint(text: str, style: str) -> str:
        return f"{style}{text}{RESET}" if color else text

    if listing:
        if as_json:
            print(json.dumps({"checks": [asdict(spec) for spec in CHECKS]}, indent=2))
            return 0
        specs = {spec.id: spec for spec in CHECKS}
        print()
        rows: list[tuple[object, ...]] = []
        for group, ids in GROUPS.items():
            rows.append(((group, BOLD),))
            for spec in map(specs.__getitem__, ids):
                needs = "session" if spec.in_session else "configuration"
                rows.append((spec.id, needs if spec.needs_configuration else "-", spec.title))
        _table(("CHECK", "NEEDS", "TITLE"), rows, paint)
        return 0

    from alphaavatar.agents.env import init_env
    from alphaavatar.host import doctor as diagnosis

    # The same .env that config check and start read; a failure to read it is reported.
    prepared = diagnosis.prepare(target, overrides, read_env=init_env)
    interrupted = False
    if prepared.starts:
        from alphaavatar.host.application.signals import shutdown_signals

        async def run():
            stop = asyncio.Event()
            # Ctrl+C stops the diagnostic session; closing what runs is never interrupted.
            with shutdown_signals(stop.set):
                return await prepared.run(stop=stop), stop.is_set()

        report, interrupted = asyncio.run(run())
    else:
        # Nothing to start: no event loop, so no local socket is opened either.
        report = prepared.report()
    code = 130 if interrupted else report.exit_code
    if as_json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return code

    counts = report.counts()
    # Interrupted: what ran is reported; the rest did not run.
    style = _STYLES[CheckStatus.WARN if interrupted else report.status]
    label = "OK" if report.status == CheckStatus.PASS else report.status
    label = "STOPPED" if interrupted else label
    print(
        f"\n{paint(label, BOLD + style)}  doctor: {counts[CheckStatus.PASS]} passed, "
        f"{counts[CheckStatus.WARN]} warned, {counts[CheckStatus.FAIL]} failed, "
        f"{counts[CheckStatus.SKIP]} not verified or skipped"
        f"{' (interrupted)' if interrupted else ''}\n"
    )
    checks = {check.id: check for check in report.checks}
    _table(("STATUS", "CHECK", "SUMMARY"), _check_rows(checks), paint)
    runners = checks["models.runners"].runners
    if runners:
        _table(
            ("STATUS", "RUNNER", "CONFIGURATION", "STARTUP", "SUMMARY"),
            [
                (
                    (runner.status, _STYLES[runner.status]),
                    runner.method,
                    runner.configuration,
                    f"{runner.startup_seconds:.2f} s"
                    if runner.startup_seconds is not None
                    else "-",
                    runner.summary,
                )
                for runner in runners
            ],
            paint,
        )
    services = checks["services.external"].services
    if services:
        _table(
            ("SERVICE", "AUTHORIZED", "REACHED", "PASSED", "NOTE"),
            [
                (
                    service.name,
                    _state(service.authorized),
                    _state(service.reached),
                    _state(service.passed),
                    service.note or "",
                )
                for service in services
            ],
            paint,
        )
    scenarios = checks["session.scenarios"].scenarios
    if scenarios:
        _table(
            ("OUTCOME", "SCENARIO", "CONFIGURATION", "SUMMARY"), _scenario_rows(scenarios), paint
        )
        _figures(scenarios, paint)
    return code


def _table(header: Sequence[str], rows: Sequence[Sequence[object]], paint) -> None:
    """Columns as wide as their widest cell, the last one free. A cell is text, or text and
    its style; a row of one cell is a heading across the table."""

    def text(cell: object) -> str:
        return cell if isinstance(cell, str) else cell[0]

    cells = [[text(cell) for cell in row] for row in rows if len(row) > 1]
    widths = [max(len(row[i]) for row in (header, *cells)) for i in range(len(header) - 1)]
    rule = max((len(row[-1]) for row in (header, *cells)), default=0)

    def line(row: Sequence[object]) -> str:
        parts = []
        for index, cell in enumerate(row):
            value, style = (cell, None) if isinstance(cell, str) else cell
            padded = value.ljust(widths[index]) if index < len(widths) and len(row) > 1 else value
            parts.append(paint(padded, style) if style and value else padded)
        return f"    {'  '.join(parts)}".rstrip()

    print(line([(name, BOLD) for name in header]))
    print(f"    {'  '.join('-' * width for width in (*widths, min(rule, 60)))}".rstrip())
    for row in rows:
        print(line(row))
    print()


def _check_rows(checks) -> list[tuple[object, ...]]:
    """Grouped; a pass is its row, anything else adds its details and next step below."""
    rows: list[tuple[object, ...]] = []
    for group, ids in GROUPS.items():
        rows.append(((group, BOLD),))
        for check in map(checks.__getitem__, ids):
            rows.append(((check.status, _STYLES[check.status]), check.id, check.summary))
            if check.status == CheckStatus.PASS:
                continue  # A pass is its summary; the details stay in --json.
            # The services table shows each service; the rest of the details stay here.
            tabled = tuple(f"{service.name}:" for service in check.services)
            for detail in check.details:
                if not tabled or not detail.startswith(tabled):
                    rows.append(("", "", (detail, DIM)))
            if check.action is not None:
                rows.append(("", "", f"-> {check.action}"))
    return rows


def _scenario_rows(scenarios) -> list[tuple[object, ...]]:
    """Each scenario; a failed one adds what stopped it."""
    rows: list[tuple[object, ...]] = []
    for result in scenarios:
        outcome = (result.outcome.value.replace("_", " "), _OUTCOMES.get(result.outcome, DIM))
        rows.append((outcome, result.name, result.configuration, result.summary))
        if result.outcome != ScenarioOutcome.FAILED:
            continue
        named = result.cause is None or any(result.cause in line for line in result.details)
        cause = () if named else (f"cause: {result.cause}",)
        for line in (*result.details, *cause):
            rows.append(("", "", "", (line, DIM)))
    return rows


def _figures(scenarios, paint) -> None:
    """Measured scenarios side by side: a figure not observed is a dash."""
    measured = [
        result
        for result in scenarios
        if result.outcome in (ScenarioOutcome.PASSED, ScenarioOutcome.FAILED)
    ]
    if not measured:
        return
    values = [
        {metric.name: metric.value for metric in (*result.metrics, *result.segments)}
        for result in measured
    ]
    rows = [
        (name, *(_ms(found.get(name)) for found in values))
        for name in _FIGURES
        if any(found.get(name) is not None for found in values)
    ]
    if not rows:
        return
    names = [
        result.name
        if result.configuration == "original"
        else f"{result.name} [{result.configuration.removeprefix('degraded: ')}]"
        for result in measured
    ]
    # The last column runs free; a figures table keeps every column aligned instead.
    _table(("FIGURE (ms)", *names, ""), [(*row, "") for row in rows], paint)


def _ms(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}" if abs(value) < 10 else f"{value:.0f}"


def _state(value: bool | None) -> str:
    return "yes" if value else "no" if value is False else "-"
