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

Text and JSON show the same report, already through the configuration output boundary; the
text groups it through the shared renderer (``cli.render``), and ``--json`` keeps every event
boundary, sample count and piece of evidence. Exit codes: 0 nothing failed, 1 a check
failed, 2 invalid arguments, 130 interrupted (the report still shows what ran).
"""

from __future__ import annotations

import asyncio
import json
import shlex
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from alphaavatar.host.cli.render import STATUS, Report
from alphaavatar.host.doctor import CheckStatus, ScenarioOutcome

# Text groups only; JSON keeps the flat list and the stable check IDs.
GROUPS = {
    "Environment": ("system.platform", "python.version", "packages.alphaavatar"),
    "Configuration": ("config.load", "config.runners", "packages.capabilities"),
    "Directories": ("paths.home", "paths.cache", "paths.workspace"),
    "Session and services": (
        "session.start",
        "models.runners",
        "services.external",
        "session.scenarios",
        "session.cleanup",
    ),
    "Media devices": ("devices.media",),
}
_OUTCOMES = {
    ScenarioOutcome.PASSED: "PASS",
    ScenarioOutcome.FAILED: "FAIL",
    ScenarioOutcome.INTERRUPTED: "WARN",
}  # Any other outcome was not run: SKIP.
# The measured figures, in milliseconds as the session times them. End to end first: the
# first text, the first answer audio frame and the response complete.
LATENCY = (
    ("first_text", "First text"),
    ("first_audio_frame", "First audio frame"),
    ("response_final", "Response complete"),
    ("text_complete", "Text complete"),
    ("audio_last_frame", "Last audio frame"),
)
# Then each stage: speech, the Turn, Context, the model, TTS and the frames vision selected.
STAGES = (
    ("vad_close", "Speech end → VAD close"),
    ("stt_final", "Speech end → STT final"),
    ("turn_cutoff", "Speech end → Turn commit"),
    ("last_required_input", "Speech end → Last required input"),
    ("context_ready_wait", "Context ready wait"),
    ("cutoff_to_model_request", "Turn commit → Model request"),
    ("model_first_event", "Model request → First event"),
    ("model_first_text_delta", "Model request → First text delta"),
    ("first_displayable_text", "Model request → First text out"),
    ("tts_request_to_first_pcm", "TTS request → First PCM"),
    ("tts_request_to_first_audio_frame", "TTS request → First audio frame"),
    ("selected_frame_age", "Selected frame age at model request"),
    ("last_selected_frame_to_cutoff", "Newest selected frame → Turn commit"),
)
_TALLY = (
    (CheckStatus.PASS, "passed"),
    (CheckStatus.WARN, "warned"),
    (CheckStatus.FAIL, "failed"),
    (CheckStatus.SKIP, "skipped"),
)


def doctor(target: str | None, overrides: Sequence[str], *, as_json: bool, listing: bool) -> int:
    from alphaavatar.host.doctor import CHECKS

    if listing:
        if as_json:
            print(json.dumps({"checks": [asdict(spec) for spec in CHECKS]}, indent=2))
            return 0
        out = Report()
        out.title("Doctor checks")
        specs = {spec.id: spec for spec in CHECKS}
        column = out.column(list(specs))
        for group, ids in GROUPS.items():
            out.heading(group)
            for spec in map(specs.__getitem__, ids):
                needs = "the session" if spec.in_session else "a configuration"
                needs = f" · needs {needs}" if spec.needs_configuration else ""
                out.row(spec.id, spec.title + needs, column=column)
        out.write()
        return 0

    from functools import partial

    from alphaavatar.host import doctor as diagnosis
    from alphaavatar.host.configs.credentials import load_environment

    # The same .env and credentials config check and start read; a failure is reported.
    prepared = diagnosis.prepare(target, overrides, read_env=partial(load_environment, overrides))
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
    _text(report, prepared, [*([target] if target is not None else []), *overrides], interrupted)
    return code


def _text(report, prepared, argv: Sequence[str], interrupted: bool) -> None:
    from alphaavatar.host.configs import output_scrubber

    out = Report()
    checks = {check.id: check for check in report.checks}
    counts = report.counts()
    ran = checks["session.start"].status != CheckStatus.SKIP
    tally = " · ".join(
        f"{counts[status]} {word}"
        for status, word in _TALLY
        if counts[status] or status == CheckStatus.PASS
    )
    out.title("Doctor")
    if interrupted:  # What ran is reported; the rest did not run.
        out.status("WARN", f"Interrupted · {tally}")
    else:
        status = "OK" if report.status == CheckStatus.PASS else str(report.status)
        out.status(status, f"Diagnostics completed · {tally}" if ran else tally)

    groups = {title: [checks[i] for i in ids] for title, ids in GROUPS.items()}
    tested = {
        title: group
        for title, group in groups.items()
        if any(check.status != CheckStatus.SKIP for check in group)
    }
    scenarios = checks["session.scenarios"].scenarios
    if checks["session.scenarios"].status == CheckStatus.SKIP:
        scenarios = ()  # Not run: the session's reason says why.
    names = {id(result): _name(result) for result in scenarios}
    column = out.column([*groups, *names.values()])

    out.heading("Checks")
    for title, group in tested.items():
        out.row(title, _summary(title, group, prepared), status=_worst(group), column=column)
        details = out.column([check.id for check in group])
        for check in group:
            if check.status != CheckStatus.PASS:  # A pass is its group's; details in --json.
                _check(out, check, details)
    if skipped := {title: group for title, group in groups.items() if title not in tested}:
        out.heading("Not verified")
        for title, group in skipped.items():
            cause = group[0]  # What the rest of the group follows from.
            out.row(title, status="SKIP")
            _explained(out, cause, indent=2 + STATUS)

    if scenarios:
        out.heading("Scenarios")
        for result in scenarios:
            status = _OUTCOMES.get(result.outcome, "SKIP")
            shown = _covers(result) if status == "PASS" else result.summary
            out.row(names[id(result)], shown, status=status, column=column)
            if result.outcome == ScenarioOutcome.FAILED:
                named = result.cause is None or any(result.cause in line for line in result.details)
                for line in (*result.details, *(() if named else (f"cause: {result.cause}",))):
                    out.note(line, indent=2 + STATUS)

    if runners := checks["models.runners"].runners:
        out.heading("Runners")
        width = out.column([runner.method for runner in runners])
        for runner in runners:
            shown = runner.summary
            if runner.status == CheckStatus.PASS and runner.startup_seconds is not None:
                shown = f"started in {runner.startup_seconds:.2f} s"
            if runner.configuration != "original":
                shown += f" · {runner.configuration}"
            out.row(runner.method, shown, status=str(runner.status), column=width)
            if runner.status != CheckStatus.PASS:
                for line in runner.details:
                    out.note(line, indent=2 + STATUS)

    measured = [
        result
        for result in scenarios
        if result.outcome in (ScenarioOutcome.PASSED, ScenarioOutcome.FAILED)
    ]
    out.heading("End-to-end latency")
    if not measured:
        why = "No scenario was measured." if ran else "Diagnostic session did not run."
        out.write(f"  Not measured · {why}")
    else:
        _latency(out, [names[id(result)] for result in measured], measured)
        # Each scenario's stages, aligned with the others'.
        stages = [_figures(result) for result in measured]
        column = out.column([label for name, label in STAGES if any(name in f for f in stages)])
        for result, found in zip(measured, stages, strict=True):
            rows = [(label, [_ms(found[name])]) for name, label in STAGES if name in found]
            if rows:
                out.heading(f"Stage timing · {names[id(result)]}")
                out.table(None, rows, fit=False, column=column)

    scrub = output_scrubber(prepared.loaded[0] if prepared.loaded is not None else None)
    out.heading("Full report")
    out.command(scrub(shlex.join(["alphaavatar", "doctor", *argv, "--json"])))
    out.write()


def _worst(group) -> str:
    statuses = {check.status for check in group}
    for status in (CheckStatus.FAIL, CheckStatus.WARN, CheckStatus.PASS):
        if status in statuses:
            return str(status)
    return "SKIP"


def _summary(title: str, group, prepared) -> str:
    """A group on one line: what passed, or how many of each."""
    if any(check.status != CheckStatus.PASS for check in group):
        return " · ".join(
            f"{count} {word}"
            for status, word in _TALLY
            if (count := sum(check.status == status for check in group))
        )
    if title == "Configuration" and prepared.loaded is not None:
        from alphaavatar.agents.runtime.inference import plan_inference_runners

        config, source = prepared.loaded
        name = source.bundle if source.bundle is not None else Path(source.path).name
        count = len(plan_inference_runners(config.avatar))
        return f"{name} · {count} runner{'' if count == 1 else 's'}"
    return f"{len(group)} checks passed"


def _check(out: Report, check, column: int) -> None:
    """A check that did not pass, under its group: its summary, details and next step."""
    out.row(check.id, check.summary, status=str(check.status), indent=2 + STATUS, column=column)
    _explained(out, check, indent=2 + 2 * STATUS, summary=False)


def _explained(out: Report, check, *, indent: int, summary: bool = True) -> None:
    if summary:
        out.wrapped(check.summary, indent=indent)
    for detail in check.details:
        out.note(detail, indent=indent)
    if check.action is not None:
        out.wrapped(f"→ {check.action}", indent=indent)


def _name(result) -> str:
    if result.configuration == "original":
        return result.name
    return f"{result.name} [{result.configuration.removeprefix('degraded: ')}]"


def _covers(result) -> str:
    """What a scenario that passed showed, by its task."""
    from alphaavatar.host.doctor import samples

    tasks = (samples.VOICE_VISION, samples.VOICE, samples.TEXT)
    return next((task.covers for task in tasks if task.name == result.name), result.summary)


def _figures(result) -> dict[str, float | None]:
    return {metric.name: metric.value for metric in (*result.metrics, *result.segments)}


def _latency(out: Report, names: list[str], measured) -> None:
    """Scenarios side by side where the terminal fits them, else one after another; a figure
    not observed is a dash, never 0 ms."""
    found = [_figures(result) for result in measured]
    rows = [
        (label, [_ms(figures.get(name)) for figures in found])
        for name, label in LATENCY
        if any(name in figures for figures in found)
    ]
    if not rows or out.table(("Metric", *names), rows):
        return
    for index, name in enumerate(names):
        out.write(f"  {name}")
        out.table(None, [(label, [values[index]]) for label, values in rows], indent=4, fit=False)


def _ms(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.1f} ms" if abs(value) < 10 else f"{value:,.0f} ms"
