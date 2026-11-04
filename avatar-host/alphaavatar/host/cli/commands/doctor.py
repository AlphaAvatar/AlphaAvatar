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
# What a failed scenario shows in text: end to end, then by segment.
_SHOWN = (
    ("first_text", "first text"),
    ("first_audio_frame", "first audio"),
    ("text_complete", "text done"),
    ("audio_last_frame", "audio last"),
    ("response_final", "complete"),
    ("last_required_input", "last input"),
)
_SEGMENTS = (
    ("vad_close", "vad"),
    ("stt_final", "stt final"),
    ("turn_cutoff", "cutoff"),
    ("cutoff_to_model_request", "to request"),
    ("model_first_token", "first token"),
    ("tts_request_to_first_pcm", "tts first pcm"),
    ("selected_frame_age", "frame age"),
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
        width = max(map(len, specs))
        print()
        for group, ids in GROUPS.items():
            print(f"    {paint(group, BOLD)}")
            for spec in map(specs.__getitem__, ids):
                needs = ", in the diagnostic session" if spec.in_session else ""
                needs = f"  (needs a configuration{needs})" if spec.needs_configuration else ""
                print(f"      {spec.id.ljust(width)}  {spec.title}{needs}")
        print()
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
        f"{' (interrupted)' if interrupted else ''}"
    )
    checks = {check.id: check for check in report.checks}
    width = max(map(len, checks))
    indent = " " * (6 + 4 + 2 + width + 2)
    for group, ids in GROUPS.items():
        print(f"    {paint(group, BOLD)}")
        for check in map(checks.__getitem__, ids):
            status = paint(check.status, _STYLES[check.status])
            print(f"      {status}  {check.id.ljust(width)}  {check.summary}")
            if check.status != CheckStatus.PASS:
                _runners(check, paint)
            _scenarios(check, paint)
            if check.status == CheckStatus.PASS:
                continue  # A pass is its summary; the details stay in --json.
            for line in check.details:
                print(f"{indent}{paint(line, DIM)}")
            if check.action is not None:
                print(f"{indent}-> {check.action}")
    print()
    return code


def _runners(check, paint) -> None:
    width = max((len(runner.method) for runner in check.runners), default=0)
    for runner in check.runners:
        status = paint(runner.status, _STYLES[runner.status])
        print(f"        {status}  {runner.method.ljust(width)}  {runner.summary}")


def _scenarios(check, paint) -> None:
    """Each scenario on a line; a failed one also shows what it did observe."""
    outcomes = [result.outcome.value.replace("_", " ") for result in check.scenarios]
    width = max(map(len, outcomes), default=0)
    names = max((len(result.name) for result in check.scenarios), default=0)
    nested = " " * (8 + width + 2 + names + 2)
    for result, outcome in zip(check.scenarios, outcomes, strict=True):
        style = _OUTCOMES.get(result.outcome, DIM)
        where = "" if result.configuration == "original" else f"  [{result.configuration}]"
        print(
            f"        {paint(outcome.ljust(width), style)}  {result.name.ljust(names)}  "
            f"{result.summary}{where}"
        )
        if result.outcome != ScenarioOutcome.FAILED:
            continue
        for line in result.details:
            print(f"{nested}{paint(line, DIM)}")
        for title, metrics, shown in (
            ("end to end", result.metrics, _SHOWN),
            ("segments", result.segments, _SEGMENTS),
        ):
            values = {metric.name: metric.value for metric in metrics}
            parts = [
                f"{label} {values[name]:.0f} ms"
                for name, label in shown
                if values.get(name) is not None
            ]
            if parts:
                print(f"{nested}{paint(f'{title}: ' + '; '.join(parts), DIM)}")
