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
"""Doctor's reports side by side: one configuration against another, each run as JSON.

    python scripts/quality/doctor_compare.py NAME=REPORT.json NAME=REPORT.json ...

Each REPORT is ``alphaavatar doctor ... --json`` output, NAME what changed in it (``segment``,
``realtime``, ``frames=2``). For each scenario, a row per figure and a column per report: the
rounds passed of run, where the others stopped, and each figure's median over the passed
rounds after the first, the first round's beside it. Then what the spoken turns' evidence
shows of turn taking: holds, cancels, finals that came for a retired segment, and sentences
lost, by the layer that lost them. Only what the reports hold is read; nothing is run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FIGURES = (
    ("stt_final", "Speech end → STT final"),
    ("turn_cutoff", "Speech end → Turn commit"),
    ("first_text", "Host first text"),
    ("first_audio_frame", "First audio frame"),
    ("response_final", "Response complete"),
    ("model_request_encode", "Request encoding"),
    ("model_request_frames", "Pictures sent"),
    ("model_request_bytes", "Request size"),
    ("model_first_event", "Model request → First event"),
    ("model_first_text_delta", "Model request → First text delta"),
)


def load(path: str) -> dict:
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    checks = {check["id"]: check for check in report["checks"]}
    return checks["session.scenarios"]


def turn_taking(scenarios: list[dict], name: str) -> dict[str, int]:
    """What the spoken rounds' evidence counts: decisions, retired finals, lost sentences."""
    found = {"holds": 0, "cancels": 0, "retired finals": 0}
    for result in scenarios:
        if result["name"] != name or result.get("round") is None:
            continue
        for item in result.get("evidence") or ():
            action = (item.get("detail") or {}).get("action")
            if item["stage"] == "candidate.decision" and action in ("hold", "cancel"):
                found["holds" if action == "hold" else "cancels"] += 1
            if item["stage"] == "candidate.transcript_rejected":
                found["retired finals"] += 1
        for sentence in result.get("sentences") or ():
            if not sentence["heard"]:
                key = f"sentences lost in {sentence['lost']}"
                found[key] = found.get(key, 0) + 1
    return found


def value(figure: dict | None, unit: str) -> str:
    if figure is None or (figure["first"] is None and not figure["samples"]):
        return "—"

    def shown(number: float | None) -> str:
        if number is None:
            return "—"
        if unit == "frames":
            return f"{int(number)}"
        return f"{number:,.1f}" if unit == "ms" and abs(number) < 10 else f"{number:,.0f}"

    return f"{shown(figure['median'])} ({shown(figure['first'])})"


def compare(reports: list[tuple[str, dict]]) -> list[str]:
    lines = []
    names = list(dict.fromkeys(s["name"] for _, r in reports for s in r["summaries"]))
    for name in names:
        lines.append(
            f"{name}: the later rounds' median (round 1), ms; pictures counted, sizes in bytes"
        )
        rows = [("Rounds passed", [])]
        for _, report in reports:
            summary = next(
                (
                    s
                    for s in report["summaries"]
                    if s["name"] == name and s["configuration"] == "original"
                ),
                None,
            )
            stopped = ", ".join(
                f"{n} at {stage}" for stage, n in (summary or {}).get("stopped_at", {}).items()
            )
            rows[0][1].append(
                f"{summary['passed']}/{summary['rounds']}" + (f"; {stopped}" if stopped else "")
                if summary
                else "—"
            )
        for key, label in FIGURES:
            cells = []
            for _, report in reports:
                summary = next(
                    (
                        s
                        for s in report["summaries"]
                        if s["name"] == name and s["configuration"] == "original"
                    ),
                    None,
                )
                figure = next(
                    (f for f in (summary or {}).get("figures", ()) if f["name"] == key), None
                )
                cells.append(value(figure, figure["unit"] if figure else "ms"))
            if any(cell != "—" for cell in cells):
                rows.append((label, cells))
        counts = [turn_taking(report["scenarios"], name) for _, report in reports]
        for key in dict.fromkeys(k for c in counts for k in c):
            rows.append((key.capitalize(), [str(c.get(key, 0)) for c in counts]))
        width = max(len(label) for label, _ in rows) + 2
        columns = [
            max(len(label), *(len(r[1][i]) for r in rows)) for i, (label, _) in enumerate(reports)
        ]
        lines.append(
            " " * width
            + "  ".join(label.rjust(w) for (label, _), w in zip(reports, columns, strict=False))
        )
        for label, cells in rows:
            lines.append(
                label.ljust(width)
                + "  ".join(c.rjust(w) for c, w in zip(cells, columns, strict=False))
            )
        lines.append("")
    return lines


def main(argv: list[str]) -> int:
    if not argv or any("=" not in arg for arg in argv):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    reports = [(name, load(path)) for name, path in (arg.split("=", 1) for arg in argv)]
    print("\n".join(compare(reports)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
