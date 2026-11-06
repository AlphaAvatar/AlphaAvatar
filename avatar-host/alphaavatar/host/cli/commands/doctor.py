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
import sys
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


def doctor(
    target: str | None,
    overrides: Sequence[str],
    *,
    as_json: bool,
    listing: bool,
    metrics: bool = True,
) -> int:
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

    from alphaavatar.agents.utils.files.model.model_files import models_offline
    from alphaavatar.host import doctor as diagnosis
    from alphaavatar.host.configs.credentials import load_environment

    # The text report, and the questions before it; with --json, stdout is the JSON alone.
    out = Report(sys.stderr if as_json else sys.stdout)
    asking = sys.stdin.isatty()
    if not as_json:
        out.title("Doctor")
    titled = out.lines
    # The same .env and credentials config check and start read; a failure is reported.
    prepared = diagnosis.prepare(target, overrides, read_env=partial(load_environment, overrides))
    skipped, interrupted = None, False
    try:
        if not metrics:
            skipped = "left out with --no-metrics"
        elif services := prepared.unauthorized:
            # A person agrees to what may be billed; without one, only the configuration does.
            if asking and _agreed(out, services, titled=not as_json):
                prepared = prepared.authorized()
            elif asking:
                skipped = "the external services it reaches were declined"
        if skipped is None and prepared.starts:
            report, interrupted = _run(out, prepared, downloads=False)
            missing = diagnosis.missing_models(report)
            # Offered unless downloads are switched off here (ALPHAAVATAR_MODEL_OFFLINE).
            offer = missing and asking and not interrupted and not models_offline()
            if offer and _download(out, missing, prepared):
                report, interrupted = _run(out, prepared, downloads=True)
        else:
            # Nothing to start: no event loop, so no local socket is opened either.
            report = prepared.report(skipped)
    except KeyboardInterrupt:
        report, interrupted = prepared.report("interrupted at a question"), True
    code = 130 if interrupted else report.exit_code
    if as_json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return code
    if out.lines > titled:  # Questions came first: the report stands apart from them.
        out.write()
    _text(out, report, prepared, target, bool(overrides), interrupted)
    return code


def _agreed(out: Report, services: Sequence[str], *, titled: bool) -> bool:
    """Whether a person agrees to the runtime tests reaching ``services``."""
    if not titled:
        out.title("Doctor")
    out.heading("Runtime tests")
    out.wrapped(
        "They run this configuration on fixed samples, through the services it names:", indent=2
    )
    for name in services:
        out.wrapped(name, indent=4)
    out.wrapped("Calls to these services may be billed.", indent=2)
    return _yes(out, "Run the runtime tests?")


def _download(out: Report, missing: Sequence[str], prepared) -> bool:
    """Whether a person agrees to download the model files the runners lack."""
    from alphaavatar.host.cli.render import home_relative

    out.heading("Model files")
    out.wrapped(
        "These runners did not start: their model files are not in the cache yet.", indent=2
    )
    for method in missing:
        out.wrapped(method, indent=4)
    cache = home_relative(prepared.loaded[0].paths.cache.root / "models")
    out.wrapped(
        f"Doctor downloads what the runners need into {cache}, as start would, then runs the "
        "runtime tests again.",
        indent=2,
    )
    return _yes(out, "Download and continue?")


def _yes(out: Report, question: str) -> bool:
    while (answer := out.ask(f"{question} [y/N]: ").strip().lower()) not in (
        "",
        "y",
        "yes",
        "n",
        "no",
    ):
        pass
    return answer.startswith("y")


def _run(out: Report, prepared, *, downloads: bool):
    """The report of one run, and whether Ctrl+C stopped it."""
    from alphaavatar.host.application.signals import shutdown_signals

    async def run():
        stop = asyncio.Event()
        # Ctrl+C stops the diagnostic session; closing what runs is never interrupted.
        with shutdown_signals(stop.set):
            return await prepared.run(stop=stop, downloads=downloads), stop.is_set()

    if downloads:
        out.pending("Downloading the model files, then running the runtime tests…")
    else:
        out.pending("Running the runtime tests on fixed samples…")
    return asyncio.run(run())


def _text(
    out: Report, report, prepared, target: str | None, overridden: bool, interrupted: bool
) -> None:
    checks = {check.id: check for check in report.checks}
    counts = report.counts()
    ran = checks["session.start"].status != CheckStatus.SKIP
    tally = " · ".join(
        f"{counts[status]} {word}"
        for status, word in _TALLY
        if counts[status] or status == CheckStatus.PASS
    )
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
        why = "no scenario was measured" if ran else checks["session.start"].summary
        out.wrapped(f"Not measured · {why}", indent=2)
    else:
        _latency(out, [names[id(result)] for result in measured], measured)
        # Each scenario's stages, aligned with the others'.
        stages = [_figures(result) for result in measured]
        column = out.column([label for name, label in STAGES if any(name in f for f in stages)])
        for result, found in zip(measured, stages, strict=True):
            shown = [(name, label) for name, label in STAGES if name in found]
            if shown:
                out.heading(f"Stage timing · {names[id(result)]}")
                rows = [(label, [_ms(found[name].value)]) for name, label in shown]
                out.table(None, rows, fit=False, column=column)
                _unobserved(out, [(label, [(result, found[name])]) for name, label in shown])

    # Every event boundary, sample count and piece of evidence: the diagnosis run again. The
    # overrides are not repeated, whatever they hold.
    out.heading("Run again as JSON")
    out.command(shlex.join(["alphaavatar", "doctor", *([target] if target else []), "--json"]))
    if overridden:
        out.note("With the same KEY=VALUE overrides, which are not repeated here.", indent=2)
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


def _figures(result) -> dict:
    return {metric.name: metric for metric in (*result.metrics, *result.segments)}


def _latency(out: Report, names: list[str], measured) -> None:
    """Scenarios side by side where the terminal fits them, else one after another; a figure
    not observed is a dash, never 0 ms, and why follows."""
    found = [_figures(result) for result in measured]
    shown = [(name, label) for name, label in LATENCY if any(name in f for f in found)]
    if not shown:
        return
    rows = [
        (label, [_ms(f[name].value if name in f else None) for f in found]) for name, label in shown
    ]
    if not out.table(("Metric", *names), rows):
        for index, name in enumerate(names):
            out.write(f"  {name}")
            single = [(label, [values[index]]) for label, values in rows]
            out.table(None, single, indent=4, fit=False)
    figures = [
        (label, [(r, f.get(name)) for r, f in zip(measured, found, strict=True)])
        for name, label in shown
    ]
    _unobserved(out, figures, names)


def _unobserved(out: Report, figures, names: Sequence[str] | None = None) -> None:
    """Why each dash is one: the figure's own note, or where its scenario stopped."""
    reasons: dict[tuple[str, str], list[str]] = {}
    for label, cells in figures:
        for result, metric in cells:
            if metric is not None and metric.value is not None:
                continue
            if metric is not None and metric.note:
                why = metric.note
            elif result.outcome == ScenarioOutcome.FAILED and result.blocked_stage:
                why = f"not reached: stopped at {result.blocked_stage}"
            else:
                why = "not observed"
            reasons.setdefault((label, why), []).append(_name(result))
    for (label, why), scenarios in reasons.items():
        where = f" · {', '.join(scenarios)}" if names is not None and len(names) > 1 else ""
        out.note(f"— {label}{where}: {why}", indent=2)


def _ms(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.1f} ms" if abs(value) < 10 else f"{value:,.0f} ms"
