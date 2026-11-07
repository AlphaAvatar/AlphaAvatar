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
# The measured figures, in milliseconds as the session times them, all from the last voiced
# sample. End to end first, as the session's output boundary saw it.
LATENCY = (
    ("first_text", "Runtime first text"),
    ("first_audio_frame", "First audio frame"),
    ("response_final", "Response complete"),
    ("text_complete", "Text complete"),
    ("audio_last_frame", "Last audio frame"),
)


def _stages() -> tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...]:
    """Each stage of the chain to the first audio frame: its total, then its rows, each
    from the node before; with every boundary, the totals add up to the first audio frame."""
    from alphaavatar.host.doctor.measure import NODES, STAGES

    return tuple(
        (
            stage,
            title,
            tuple(
                (f"{stage}.{NODES[at][0]}", f"{NODES[at - 1][1]} → {NODES[at][1]}")
                for at in range(first + 1, last + 1)
            ),
        )
        for stage, title, first, last in STAGES
    )


# What to do about a scenario that stopped, by the stage it stopped at.
_NEXT = (
    ("runners", "See Runners: the first that did not start, and why"),
    ("input", "The sample did not go in: see the session's details"),
    ("vad.closed", "No speech segment closed: check voice.vad and its runner"),
    (
        "stt.final",
        "See the transcript and each sentence in --json; another STT model or plugin compares",
    ),
    ("transcript", "See each sentence's evidence in --json: where it was lost is not shown"),
    ("turn.committed", "Turn taking did not commit: see the candidate decisions in --json"),
    ("frames", "No picture reached the request: check vision and its input mode"),
    ("model", "The model request failed: see its cause above"),
    ("request", "The request lacks the turn's input: see request in --json"),
    ("answer", "See the transcript and the answer in --json"),
    ("turn.timeout", "The turn did not end in time: see where its evidence stops in --json"),
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
    rounds: int = 5,
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

    from alphaavatar.host import doctor as diagnosis
    from alphaavatar.host.configs.credentials import load_environment

    # The text report, and the question before it; with --json, stdout is the JSON alone.
    out = Report(sys.stderr if as_json else sys.stdout)
    asking = sys.stdin.isatty()
    if not as_json:
        out.title("Doctor")
    titled = out.lines
    # The same .env and credentials config check and start read; a failure is reported.
    prepared = diagnosis.prepare(
        target, overrides, read_env=partial(load_environment, overrides), rounds=rounds
    )
    skipped, interrupted = None, False
    try:
        if not metrics:
            skipped = "left out with --no-metrics"
        elif prepared.asks and asking:
            # One question for the whole batch: what runs, what it may download and call.
            if _agreed(out, prepared, titled=not as_json):
                prepared = prepared.authorized()
            else:
                skipped = "the diagnosis was declined"
        if skipped is None and prepared.starts:
            report, interrupted = _run(out, prepared)
        else:
            # Nothing to start: no event loop, so no local socket is opened either.
            report = prepared.report(skipped)
    except KeyboardInterrupt:
        report, interrupted = prepared.report("interrupted at a question"), True
    code = 130 if interrupted else report.exit_code
    if as_json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return code
    if out.lines > titled:  # The question came first: the report stands apart from it.
        out.write()
    _text(out, report, prepared, target, bool(overrides), interrupted)
    return code


def _agreed(out: Report, prepared, *, titled: bool) -> bool:
    """Whether a person agrees to the whole diagnosis: its scenarios and rounds, the model
    files it may download, the services it calls."""
    if not titled:
        out.title("Doctor")
    out.heading("Runtime diagnosis")
    rounds = prepared.rounds
    each = f"{rounds} times" if rounds > 1 else "once"
    out.wrapped(
        f"It starts this bundle's runtime as start does, then runs this scenario {each}, each "
        "time in a session of its own:",
        indent=2,
    )
    width = out.column([name for name, _ in prepared.scenarios])
    for name, covers in prepared.scenarios:
        out.row(name, covers, indent=4, column=width)
    out.wrapped("Model files the cache lacks are downloaded first, as start would.", indent=2)
    if services := prepared.services:
        out.wrapped("It calls the services this configuration names:", indent=2)
        for name in services:
            out.wrapped(name, indent=4)
        out.wrapped("Calls to these services may be billed.", indent=2)
    return _yes(out, "Run the diagnosis?")


def _yes(out: Report, question: str) -> bool:
    """Yes only when typed; Enter, no, or the input ending (EOF) declines."""
    try:
        while (answer := out.ask(f"{question} [y/N]: ").strip().lower()) not in (
            "",
            "y",
            "yes",
            "n",
            "no",
        ):
            pass
    except EOFError:
        return False
    return answer.startswith("y")


def _run(out: Report, prepared):
    """The report of one diagnosis, and whether Ctrl+C stopped it."""
    from alphaavatar.host.application.signals import shutdown_signals

    async def run():
        stop = asyncio.Event()
        # Ctrl+C stops the diagnosis; closing what runs is never interrupted.
        with shutdown_signals(stop.set):
            return await prepared.run(stop=stop), stop.is_set()

    each = f"{prepared.rounds} rounds of its scenario" if prepared.rounds > 1 else "its scenario"
    out.pending(f"Starting the runtime, then running {each}…")
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
    column = out.column([*groups, *(result.name for result in scenarios)])

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

    # In the order a turn depends on them: the sessions, the runners, then each scenario.
    ready = next((m for m in checks["session.start"].metrics if m.name == "session_ready"), None)
    if ready is not None and ready.value is not None:
        out.heading("Session")
        spread = (
            f" at the median of {ready.samples}, {_range('ms', min(ready.values), max(ready.values))}"
            if ready.samples > 1
            else ""
        )
        out.row("Ready", f"{_ms(ready.value)}{spread}", column=column)
    runners = checks["models.runners"].runners
    starts = [m for m in checks["models.runners"].metrics if m.name == "runtime_start"]
    if runners or starts:
        out.heading("Runners")
        for start in starts:
            shown = f"{_ms(start.value)} · {start.note}" if start.value is not None else "—"
            out.row("Runtime start", shown, column=column)
        width = out.column([runner.method for runner in runners])
        for runner in runners:
            shown = runner.summary
            if runner.status == CheckStatus.PASS and runner.startup_seconds is not None:
                shown = f"started in {runner.startup_seconds:.2f} s"
                if runner.calls:
                    shown += (
                        f" · {runner.calls} calls, queue ≤ {_ms(runner.queue_wait_max_ms)}, "
                        f"run ≤ {_ms(runner.execution_max_ms)}"
                    )
            out.row(runner.method, shown, status=str(runner.status), column=width)
            if runner.status != CheckStatus.PASS:
                for line in runner.details:
                    out.note(line, indent=2 + STATUS)

    summaries = checks["session.scenarios"].summaries if scenarios else ()
    by = {x.name: x for x in summaries}
    if scenarios:
        rounds = max((x.rounds for x in summaries), default=0)
        each = f" · {rounds} rounds, a session each" if rounds > 1 else ""
        out.heading(f"Scenarios{each}")
        shown_once = set()
        for result in scenarios:
            if result.round is not None:
                if result.name not in shown_once:
                    shown_once.add(result.name)
                    found = [r for r in scenarios if r.name == result.name]
                    _summary_row(out, by[result.name], found, column)
                continue
            status = _OUTCOMES.get(result.outcome, "SKIP")
            out.row(result.name, result.summary, status=status, column=column)
        for summary in summaries:  # What the rounds ran with, and the recording they heard.
            out.wrapped(f"With {summary.configuration}", indent=2)
            if summary.sample:
                out.wrapped(f"Sample {summary.sample}", indent=2)

    observed = [x for x in summaries if any(f.all_first or f.all_samples for f in x.figures)]
    if not observed:
        out.heading("Latency")
        why = "no scenario was measured" if ran else checks["session.start"].summary
        if summaries and ran:
            why = "no round observed any figure"
        out.wrapped(f"Not measured · {why}", indent=2)
    for summary in observed:
        if summary.passed:
            _figures_table(out, summary)
        if summary.passed < summary.rounds:
            _figures_table(out, summary, every=True)
    for summary in summaries:
        failed = [
            r for r in scenarios if r.name == summary.name and r.outcome == ScenarioOutcome.FAILED
        ]
        if failed:
            out.heading(f"Failed rounds · {summary.name}")
            for result in failed:
                measured = _measured(result)
                out.wrapped(
                    f"Round {result.round} · stopped at {result.blocked_stage}"
                    + (f" · measured: {measured}" if measured else " · nothing measured"),
                    indent=2,
                )

    # Every event boundary, sample count and piece of evidence: the diagnosis run again, as
    # many rounds. The overrides are not repeated, whatever they hold.
    out.heading("Run again as JSON")
    again = ["alphaavatar", "doctor", *([target] if target else [])]
    out.command(shlex.join([*again, "--rounds", str(prepared.rounds), "--json"]))
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


def _covers(result) -> str:
    """What a scenario that passed showed, by its task."""
    from alphaavatar.host.doctor import samples

    tasks = (samples.VOICE_VISION, samples.VOICE)
    return next((task.covers for task in tasks if task.name == result.name), result.summary)


def _figures(result) -> dict:
    return {metric.name: metric for metric in (*result.metrics, *result.segments)}


def _summary_row(out: Report, summary, results, column: int) -> None:
    """A scenario's rounds on one line: passed of run, where the others stopped; the failed
    rounds' reasons below it, each once, with the rounds that share it; then the next step."""
    name = summary.name
    failed = [r for r in results if r.outcome == ScenarioOutcome.FAILED]
    others = [
        r for r in results if r.outcome not in (ScenarioOutcome.PASSED, ScenarioOutcome.FAILED)
    ]
    status = "FAIL" if failed else "PASS" if summary.passed == summary.rounds else "WARN"
    if not summary.passed and not failed:
        status = "SKIP"
    stopped = ", ".join(f"{n} at {stage}" for stage, n in summary.stopped_at.items())
    head = f"{summary.passed}/{summary.rounds} passed"
    covers = _covers(results[0]) if summary.passed == summary.rounds else f"stopped: {stopped}"
    out.row(name, f"{head} · {covers}", status=status, column=column)
    reasons: dict[str, list[int]] = {}
    for result in (*failed, *others):
        named = result.cause is None or any(result.cause in line for line in result.details)
        lines = (*result.details, *(() if named else (f"cause: {result.cause}",)))
        for line in lines or (result.summary,):
            reasons.setdefault(line, []).append(result.round or 0)
    for line, rounds in reasons.items():
        which = "Round" if len(rounds) == 1 else "Rounds"
        out.note(f"{which} {', '.join(map(str, rounds))}: {line}", indent=2 + STATUS)
    stage = failed[0].blocked_stage if failed else ""
    step = next((s for prefix, s in _NEXT if (stage or "").startswith(prefix)), None)
    if failed and (failed[0].cause or "").endswith(": image_input"):
        step = "The model takes no pictures: choose one that does, or turn vision off"
    if failed and step:
        out.wrapped(f"→ {step}", indent=2 + STATUS)


def _figures_table(out: Report, summary, *, every: bool = False) -> None:
    """One scenario's figures over its passed rounds, or with ``every`` over every round that
    observed them, failed ones included: the first round apart, then the later rounds'
    samples, median and range, and their 95th percentile once there are enough. Each stage's
    total is on its own line, its rows below it."""
    figures = {figure.name: figure for figure in summary.figures}
    groups = (
        (None, "End to end", LATENCY),
        *((stage, title, rows) for stage, title, rows in _stages()),
    )
    p95 = not every and any(f.p95 is not None for f in summary.figures)
    header = ("Metric", "Round 1", "n", "Median", "Range", *(("P95",) * p95))
    rows, missing, merged = [], [], []

    def cells(f) -> list[str]:
        first, n, median, low, high = (
            (f.all_first, f.all_samples, f.all_median, f.all_low, f.all_high)
            if every
            else (f.first, f.samples, f.median, f.low, f.high)
        )
        if f.merged:
            merged.append((labels[f.name], f.merged))
        elif first is None and not n and f.name not in _TOTALS:
            missing.append((labels[f.name], f.note or "not observed in any such round"))
        return [
            _in(f.unit, first),
            str(n),
            _in(f.unit, median),
            _range(f.unit, low, high) if n else "—",
            *((_in(f.unit, f.p95),) * p95),
        ]

    labels = {name: label for _, _, entries in groups for name, label in entries}
    for total, group, entries in groups:
        shown = [(name, label) for name, label in entries if name in figures]
        if not shown:
            continue
        head = cells(figures[total]) if total in figures else [""] * (len(header) - 1)
        rows.append((group, head))
        rows += [(f"  {label}", cells(figures[name])) for name, label in shown]
    if every:
        failed = summary.rounds - summary.passed
        title = f"every round, the {failed} not passed included"
    else:
        title = f"{summary.passed} of {summary.rounds} rounds passed"
    out.heading(f"Latency · {summary.name} · {title}")
    if not out.table(header, rows):
        for label, values in rows:
            first, n, median, spread, *rest = values
            if not first and not n:
                out.write(f"  {label.strip()}")
                continue
            later = f" · {n} later: median {median}, {spread}" if n != "0" else ""
            # A stage's total stays at its group's level, its rows under it.
            indent = 4 if label.startswith(" ") else 2
            out.wrapped(f"{label.strip()}: round 1 {first}{later}", indent=indent)
    which = "rounds that observed it" if every else "rounds that passed and observed it"
    out.note(f"n: later {which}; the stages add up to First audio frame", indent=2)
    for label, count in merged:
        rounds = f"{count} round{'s' * (count != 1)}"
        out.note(f"— {label}: from an earlier node in {rounds}, so no sample of it", indent=2)
    # Figures missing for one reason share its line.
    reasons: dict[str, list[str]] = {}
    for label, why in missing:
        reasons.setdefault(why, []).append(label)
    for why, found in reasons.items():
        out.note(f"— {', '.join(found)}: {why}", indent=2)


_TOTALS = ("input", "context", "output")


def _measured(result) -> str:
    """What a failed round measured: end to end, then each stage's total."""
    found = _figures(result)
    labels = dict((*LATENCY, *((stage, title) for stage, title, _ in _stages())))
    shown = [
        f"{label} {_in(found[n].unit, found[n].value)}"
        for n, label in labels.items()
        if n in found and found[n].value is not None
    ]
    return "; ".join(shown)


def _in(unit: str, value: float | None) -> str:
    """A value in its unit: milliseconds, a count of pictures, or a size."""
    if value is None:
        return "—"
    if unit == "frames":
        return f"{int(value)}"
    if unit == "bytes":
        size = float(value)
        for name in ("B", "KB", "MB"):
            if size < 1000 or name == "MB":
                return f"{size:,.0f} {name}" if name == "B" else f"{size:,.1f} {name}"
            size /= 1000
    return _ms(value)


def _range(unit: str, low: float | None, high: float | None) -> str:
    if low is None or high is None:
        return "—"
    left, right = _in(unit, low), _in(unit, high)
    if left == right:  # Equal as shown
        return left
    suffix = (
        f" {right.split()[-1]}" if " " in right and left.split()[-1] == right.split()[-1] else ""
    )
    return f"{left.removesuffix(suffix)}–{right}"


def _ms(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.1f} ms" if abs(value) < 10 else f"{value:,.0f} ms"
