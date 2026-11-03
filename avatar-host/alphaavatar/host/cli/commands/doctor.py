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
2 invalid arguments, 130 runtime checks interrupted (the report still shows what ran).
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict

from alphaavatar.host.doctor import CheckStatus
from alphaavatar.host.log.format import BOLD, DIM, GREEN, RED, RESET, YELLOW, use_color

_STYLES = {
    CheckStatus.PASS: GREEN,
    CheckStatus.WARN: YELLOW,
    CheckStatus.FAIL: RED,
    CheckStatus.SKIP: DIM,
}
# Text groups only; JSON keeps the flat list and the stable check IDs.
GROUPS = {
    "environment": ("system.platform", "python.version", "packages.alphaavatar"),
    "configuration": ("config.load", "config.runners", "packages.capabilities"),
    "directories": ("paths.home", "paths.cache", "paths.workspace"),
    "runtime": ("runtime.models", "runtime.cleanup"),
    "not verified": ("models.runners", "services.external", "devices.media"),
}


def doctor(
    target: str | None,
    overrides: Sequence[str],
    *,
    as_json: bool,
    listing: bool,
    runtime: bool = False,
) -> int:
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
                needs = " and --runtime" if spec.needs_runtime else ""
                needs = f"  (needs a configuration{needs})" if spec.needs_configuration else ""
                print(f"      {spec.id.ljust(width)}  {spec.title}{needs}")
        print()
        return 0

    from alphaavatar.agents.env import init_env

    interrupted = False
    if runtime:
        from alphaavatar.host.application.signals import shutdown_signals
        from alphaavatar.host.doctor import diagnose_runtime

        async def probe():
            stop = asyncio.Event()
            # Ctrl+C stops the runtime checks; closing what runs is never interrupted.
            with shutdown_signals(stop.set):
                return await diagnose_runtime(target, overrides, read_env=init_env, stop=stop), (
                    stop.is_set()
                )

        report, interrupted = asyncio.run(probe())
    else:
        from alphaavatar.host.doctor import diagnose

        # The same .env that config check and start read; a failure to read it is reported.
        report = diagnose(target, overrides, read_env=init_env)
    code = 130 if interrupted else report.exit_code
    if as_json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return code

    counts = report.counts()
    # Interrupted: what ran is reported; the rest did not run.
    style = _STYLES[CheckStatus.WARN if interrupted else report.status]
    label = "OK" if report.status == CheckStatus.PASS else report.status
    label = "STOPPED" if interrupted else label
    scope = "static and local runtime checks" if runtime else "static checks"
    print(
        f"\n{paint(label, BOLD + style)}  doctor: {counts[CheckStatus.PASS]} passed, "
        f"{counts[CheckStatus.WARN]} warned, {counts[CheckStatus.FAIL]} failed, "
        f"{counts[CheckStatus.SKIP]} not verified or skipped "
        f"({scope}{', interrupted' if interrupted else ''})"
    )
    checks = {check.id: check for check in report.checks}
    width = max(map(len, checks))
    indent = " " * (6 + 4 + 2 + width + 2)
    for group, ids in GROUPS.items():
        if not any(check_id in checks for check_id in ids):
            continue  # The runtime group without --runtime.
        print(f"    {paint(group, BOLD)}")
        for check in (checks[check_id] for check_id in ids if check_id in checks):
            status = paint(check.status, _STYLES[check.status])
            print(f"      {status}  {check.id.ljust(width)}  {check.summary}")
            # Each runner as a check: a pass is its measurements, anything else says why.
            methods = max((len(runner.method) for runner in check.runners), default=0)
            nested = " " * (8 + 4 + 2 + methods + 2)
            for runner in check.runners:
                status = paint(runner.status, _STYLES[runner.status])
                print(f"        {status}  {runner.method.ljust(methods)}  {runner.summary}")
                if runner.status == CheckStatus.PASS:
                    continue
                for line in runner.details:
                    print(f"{nested}{paint(line, DIM)}")
                if runner.action is not None:
                    print(f"{nested}-> {runner.action}")
            if check.status == CheckStatus.PASS:
                continue  # A pass is its summary; the details stay in --json.
            for line in check.details:
                print(f"{indent}{paint(line, DIM)}")
            if check.action is not None:
                print(f"{indent}-> {check.action}")
    print()
    return code
