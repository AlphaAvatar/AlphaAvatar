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
2 invalid arguments.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from dataclasses import asdict

from alphaavatar.host.log.format import BOLD, DIM, GREEN, RED, RESET, YELLOW, use_color

_STYLES = {"PASS": GREEN, "WARN": YELLOW, "FAIL": RED, "SKIP": DIM}


def doctor(target: str | None, overrides: Sequence[str], *, as_json: bool, listing: bool) -> int:
    from alphaavatar.host.doctor import CHECKS

    if listing:
        if as_json:
            print(json.dumps({"checks": [asdict(spec) for spec in CHECKS]}, indent=2))
            return 0
        width = max(len(spec.id) for spec in CHECKS)
        print()
        for spec in CHECKS:
            needs = "  (needs a configuration)" if spec.needs_configuration else ""
            print(f"    {spec.id.ljust(width)}  {spec.title}{needs}")
        print()
        return 0

    from alphaavatar.agents.env import init_env
    from alphaavatar.host.doctor import diagnose

    init_env()  # The same .env that config check and start read for <ENV_VAR> placeholders.
    report = diagnose(target, overrides)
    if as_json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return report.exit_code

    color = use_color("auto", sys.stdout)

    def paint(text: str, style: str) -> str:
        return f"{style}{text}{RESET}" if color else text

    counts = report.counts()
    label = {"PASS": "OK", "WARN": "WARN", "FAIL": "FAIL"}[report.status]
    print(
        f"\n{paint(label, BOLD + _STYLES[report.status])}  doctor: {counts['PASS']} passed, "
        f"{counts['WARN']} warned, {counts['FAIL']} failed, {counts['SKIP']} not verified "
        "or skipped (static checks)"
    )
    width = max(len(check.id) for check in report.checks)
    indent = " " * (4 + 4 + 2 + width + 2)
    for check in report.checks:
        status = paint(check.status, _STYLES[check.status])
        print(f"    {status}  {check.id.ljust(width)}  {check.summary}")
        for line in check.details:
            print(f"{indent}{paint(line, DIM)}")
        if check.action is not None:
            print(f"{indent}-> {check.action}")
    print()
    return report.exit_code
