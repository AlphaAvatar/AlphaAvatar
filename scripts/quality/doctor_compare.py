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
``realtime``, ``frames=2``). For each scenario, a row per figure and a column per report,
recomputed from the report's own rounds as Doctor computes them: the median of the later
rounds that passed and observed it, their range and count, round 1's value apart; then the
same over every round that observed it, failed ones included. Merged values are samples of
neither. Each recomputed figure is checked against the summary the report holds; a figure
that differs is named, and the exit code is 1. Then what the rounds' evidence counts: holds,
cancels, finals for a retired segment, retried requests, and sentences lost, by the layer
that lost them. Only what the reports hold is read; nothing is run.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

# The figures compared, as Doctor's text names them: end to end, each stage and its rows,
# then what the rows leave out.
FIGURES = (
    ("first_text", "Runtime first text"),
    ("first_audio_frame", "First audio frame"),
    ("response_final", "Response complete"),
    ("input", "Input"),
    ("input.vad_close", "  Final speech → VAD close"),
    ("input.final_transcript", "  VAD close → Final transcript"),
    ("context", "Context"),
    ("context.turn_commit", "  Final transcript → Turn commit"),
    ("context.context_ready", "  Turn commit → Context readiness check complete"),
    ("context.context_built", "  Context readiness check complete → Context built"),
    ("context.request_sent", "  Context built → Model request sent"),
    ("output", "Output"),
    ("output.first_text_delta", "  Model request sent → First text delta"),
    ("output.tts_request", "  First text delta → TTS request"),
    ("output.first_pcm", "  TTS request → First PCM"),
    ("output.first_audio_frame", "  First PCM → First audio frame"),
    ("stt_request_to_final", "STT commit → Final transcript"),
    ("stt_queue", "  STT queue (commit → request started)"),
    ("stt_connect", "  STT connect (TCP)"),
    ("stt_tls", "  STT TLS handshake"),
    ("stt_upload", "  STT upload (headers → audio sent)"),
    ("stt_wait", "  STT wait (audio sent → answer's headers)"),
    ("stt_first_event", "  STT first event (headers → first event)"),
    ("stt_stream", "  STT stream (headers → transcript done)"),
    ("association_ready", "Speech closed → speaker association ready"),
    ("addressing_queue", "Semantic addressing queued → started"),
    ("addressing_inference", "Semantic addressing inference"),
    ("assessment_queue", "Speech completion assessment queued → started"),
    ("speech_completion_assessment", "Speech completion assessments, final → commit"),
    ("decision_holds", "Holds and addressing waits, final → commit"),
    ("context_ready_wait", "Context readiness wait"),
    ("model_first_event", "Model request sent → First event"),
    ("model_request_client", "Provider client ready"),
    ("model_request_prepare", "Request taken → first attempt sent"),
    ("model_request_encode", "Request encoding"),
    ("model_request_frames", "Pictures sent"),
    ("model_request_bytes", "Request size"),
    ("model_request_attempts", "Request attempts"),
)


def load(path: str) -> dict:
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    checks = {check["id"]: check for check in report["checks"]}
    return checks["session.scenarios"]


def groups(report: dict) -> dict[tuple[str, str], list[dict]]:
    """Each scenario's rounds, by scenario and the configuration they ran with."""
    found: dict[tuple[str, str], list[dict]] = {}
    for result in report["scenarios"]:
        if result.get("round") is not None:
            found.setdefault((result["name"], result["configuration"]), []).append(result)
    return found


def observed(rounds: list[dict], name: str, *, every: bool) -> tuple[float | None, list[float]]:
    """Round 1's value and the later rounds' sorted, as Doctor summarizes them: the passed
    rounds, or ``every`` round; a merged value left out."""
    kept = []
    for result in rounds:
        if not every and result["outcome"] != "passed":
            continue
        for metric in (*result.get("metrics", ()), *result.get("segments", ())):
            if metric["name"] == name and metric["value"] is not None and not metric.get("merged"):
                kept.append((result["round"], metric["value"]))
    first = next((value for at, value in kept if at == 1), None)
    return first, sorted(value for at, value in kept if at != 1)


def statistic(rounds: list[dict], name: str, *, every: bool) -> dict:
    first, later = observed(rounds, name, every=every)
    return {
        "first": first,
        "samples": len(later),
        "median": round(statistics.median(later), 3) if later else None,
        "low": later[0] if later else None,
        "high": later[-1] if later else None,
    }


def mismatches(label: str, report: dict) -> list[str]:
    """Where the report's own summaries differ from its rounds, recomputed."""
    found = []
    rounds = groups(report)
    # Each scenario's rounds, by configuration, have one summary, and no summary is without.
    keys = [(summary["name"], summary["configuration"]) for summary in report["summaries"]]
    for name, configuration in sorted(set(rounds) ^ set(keys)):
        which = "no summary" if (name, configuration) in rounds else "no rounds"
        found.append(f"{label} {name} ({configuration}): {which}")
    for name, configuration in sorted({key for key in keys if keys.count(key) > 1}):
        found.append(f"{label} {name} ({configuration}): more than one summary")
    for summary in report["summaries"]:
        key = (summary["name"], summary["configuration"])
        mine = rounds.get(key, [])
        passed = sum(r["outcome"] == "passed" for r in mine)
        if (summary["rounds"], summary["passed"]) != (len(mine), passed):
            found.append(f"{label} {key[0]}: rounds passed {summary['passed']}/{summary['rounds']}")
        stopped: dict[str, int] = {}
        for result in mine:
            if result["outcome"] != "passed":
                stage = result.get("blocked_stage") or result["outcome"]
                stopped[stage] = stopped.get(stage, 0) + 1
        if summary.get("stopped_at", {}) != stopped:
            found.append(f"{label} {key[0]}: stopped at {summary.get('stopped_at')} != {stopped}")
        # The figures summarized are the ones its rounds hold, none left out, none added.
        names = {m["name"] for r in mine for m in (*r.get("metrics", ()), *r.get("segments", ()))}
        held = {figure["name"] for figure in summary["figures"]}
        if held != names:
            missing, extra = sorted(names - held), sorted(held - names)
            found.append(f"{label} {key[0]}: figures missing {missing}, not in its rounds {extra}")
        for figure in summary["figures"]:
            for every, prefix in ((False, ""), (True, "all_")):
                held = {k: figure.get(f"{prefix}{k}") for k in ("first", "samples", "median")}
                held |= {k: figure.get(f"{prefix}{k}") for k in ("low", "high")}
                again = statistic(mine, figure["name"], every=every)
                if held != again:
                    found.append(f"{label} {key[0]} {prefix}{figure['name']}: {held} != {again}")
    return found


def events(rounds: list[dict]) -> dict[str, int]:
    """What the rounds' evidence counts: decisions, retired finals, retries, lost sentences."""
    found = {"holds": 0, "cancels": 0, "retired finals": 0, "retried requests": 0}
    for result in rounds:
        for item in result.get("evidence") or ():
            action = (item.get("detail") or {}).get("action")
            if item["stage"] == "input.decision" and action in ("hold", "cancel"):
                found["holds" if action == "hold" else "cancels"] += 1
            if item["stage"] == "input.transcript_rejected":
                found["retired finals"] += 1
        found["retried requests"] += (result.get("request") or {}).get("attempts", 0) > 1
        for sentence in result.get("sentences") or ():
            if not sentence["heard"]:
                key = f"sentences lost in {sentence['lost']}"
                found[key] = found.get(key, 0) + 1
    return found


def shown(value: float | None, unit: str) -> str:
    if value is None:
        return "—"
    if unit in ("frames", "count"):
        return f"{int(value)}"
    return f"{value:,.1f}" if unit == "ms" and abs(value) < 10 else f"{value:,.0f}"


def cell(stat: dict, unit: str) -> str:
    """median [low–high] ×n (round 1)"""
    if stat["first"] is None and not stat["samples"]:
        return "—"
    text = shown(stat["median"], unit)
    if stat["samples"] and shown(stat["low"], unit) != shown(stat["high"], unit):
        text += f" [{shown(stat['low'], unit)}–{shown(stat['high'], unit)}]"
    return f"{text} ×{stat['samples']} ({shown(stat['first'], unit)})"


def compare(reports: list[tuple[str, dict]]) -> list[str]:
    lines = []
    names = list(dict.fromkeys(key[0] for _, r in reports for key in groups(r)))
    for name in names:
        chosen = [
            next((rounds for key, rounds in groups(r).items() if key[0] == name), [])
            for _, r in reports
        ]
        units = {
            m["name"]: m["unit"]
            for rounds in chosen
            for r in rounds
            for m in (*r.get("metrics", ()), *r.get("segments", ()))
        }
        rows = [("Rounds passed", [_passed(rounds) for rounds in chosen])]
        for every, heading in ((False, "Passed rounds"), (True, "Every round, failed included")):
            rows.append((heading, [""] * len(reports)))
            for key, label in FIGURES:
                unit = units.get(key, "ms")
                cells = [cell(statistic(rounds, key, every=every), unit) for rounds in chosen]
                if any(c != "—" for c in cells):
                    rows.append((f"  {label}", cells))
        counts = [events(rounds) for rounds in chosen]
        rows.append(("Events", [""] * len(reports)))
        for key in dict.fromkeys(k for c in counts for k in c):
            rows.append((f"  {key.capitalize()}", [str(c.get(key, 0)) for c in counts]))
        lines.append(f"{name}: median [range] ×n of the later rounds (round 1), ms")
        width = max(len(label) for label, _ in rows) + 2
        columns = [
            max(len(label), *(len(cells[i]) for _, cells in rows))
            for i, (label, _) in enumerate(reports)
        ]
        lines.append(
            " " * width
            + "  ".join(label.rjust(w) for (label, _), w in zip(reports, columns, strict=True))
        )
        for label, cells in rows:
            lines.append(
                (
                    label.ljust(width)
                    + "  ".join(c.rjust(w) for c, w in zip(cells, columns, strict=True))
                ).rstrip()
            )
        for (label, _), rounds in zip(reports, chosen, strict=True):
            if rounds:
                sample = rounds[0].get("sample")
                lines.append(
                    f"{label}: {rounds[0]['configuration']}" + (f" · {sample}" if sample else "")
                )
        lines.append("")
    return lines


def _passed(rounds: list[dict]) -> str:
    if not rounds:
        return "—"
    passed = sum(r["outcome"] == "passed" for r in rounds)
    stopped: dict[str, int] = {}
    for r in rounds:
        if r["outcome"] != "passed":
            stage = r.get("blocked_stage") or r["outcome"]
            stopped[stage] = stopped.get(stage, 0) + 1
    where = ", ".join(f"{n} at {stage}" for stage, n in stopped.items())
    return f"{passed}/{len(rounds)}" + (f"; {where}" if where else "")


def main(argv: list[str]) -> int:
    if not argv or any("=" not in arg for arg in argv):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    reports = [(name, load(path)) for name, path in (arg.split("=", 1) for arg in argv)]
    print("\n".join(compare(reports)))
    differ = [line for label, report in reports for line in mismatches(label, report)]
    for line in differ:
        print(f"Differs from its summary: {line}", file=sys.stderr)
    return 1 if differ else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
