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
"""``scripts/quality/doctor_compare.py``: Doctor's JSON reports side by side, recomputed."""

from __future__ import annotations

import importlib.util
import json
from dataclasses import asdict
from pathlib import Path

from alphaavatar.host.doctor.enums import ScenarioOutcome
from alphaavatar.host.doctor.measure import summarize
from alphaavatar.host.doctor.schemas import Evidence, Metric, ScenarioResult

SCRIPT = Path(__file__).parents[3] / "scripts" / "quality" / "doctor_compare.py"


def script():
    spec = importlib.util.spec_from_file_location("doctor_compare", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def result(at: int, outcome: str, first_text: float | None, **fields) -> ScenarioResult:
    metrics = (Metric("first_text", first_text, "ms", "a", "b", "c"),)
    merged = fields.pop("merged", ())
    segments = (
        Metric("input", 500.0 + at, "ms", "a", "b", "c"),
        Metric("input.final_transcript", 200.0 + at, "ms", "a", "b", "c", merged=merged),
        Metric("model_request_encode", 0.2 + at / 100, "ms", "a", "b", "c"),
    )
    return ScenarioResult(
        "voice",
        ScenarioOutcome(outcome),
        "",
        "stt openai_segment m",
        metrics=metrics,
        segments=segments,
        round=at,
        **fields,
    )


def saved(tmp_path: Path, name: str, results: list[ScenarioResult]) -> str:
    """A report as Doctor saves it: the rounds, and the summary Doctor made of them."""
    scenarios = {
        "id": "session.scenarios",
        "scenarios": [asdict(r) for r in results],
        "summaries": [asdict(s) for s in summarize(results)],
    }
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps({"status": "FAIL", "checks": [scenarios]}))
    return f"{name}={path}"


def test_figures_and_events_are_recomputed_from_the_rounds_as_doctor_summarizes_them(
    tmp_path: Path, capsys
) -> None:
    compare = script()
    lost = {"index": 2, "heard": False, "lost": "stt"}
    cancel = Evidence(0.0, "candidate.decision", "trace", {"action": "cancel"})
    segment = [
        # The first round failed, a later one too; one merged its row; one lost a sentence.
        result(1, "failed", 900.0, sentences=(lost,)),
        result(2, "passed", 810.0, evidence=(cancel,)),
        result(3, "failed", 700.0, request={"attempts": 2}),
        result(4, "passed", None),  # Passed, the figure missing
        result(5, "passed", 830.0, merged=("vad_close",)),
    ]
    realtime = [result(at, "failed", None) for at in (1, 2)]  # Every round failed, unobserved
    paths = [saved(tmp_path, "segment", segment), saved(tmp_path, "realtime", realtime)]
    assert compare.main(paths) == 0  # Every figure as the report's own summary has it.
    lines = capsys.readouterr().out.splitlines()
    assert lines[1].split() == ["segment", "realtime"]

    def row(label: str, which: int = 0) -> list[str]:
        found = [line for line in lines if line.strip().startswith(label)]
        return [cell.strip() for cell in found[which].split("  ") if cell.strip()][1:]

    assert row("Rounds passed") == ["3/5; 2 at failed", "0/2; 2 at failed"]
    # Passed rounds: 2 and 5 observed it; round 1 failed, so no Round 1 value. Every round:
    # 2, 3 and 5 later, round 1 apart. The report that observed nothing shows nothing.
    assert row("Runtime first text") == ["820 [810–830] ×2 (—)", "—"]
    assert row("Runtime first text", 1) == ["810 [700–830] ×3 (900)", "—"]
    # The merged round is a sample of neither; sub-millisecond figures keep a decimal.
    assert row("VAD close → Final transcript") == ["203 [202–204] ×2 (—)", "—"]
    assert row("Request encoding") == ["0.2 ×3 (—)", "—"]
    assert row("Cancels") == ["1", "0"] and row("Retried requests") == ["1", "0"]
    assert row("Sentences lost in stt") == ["1", "0"]
    assert "segment: stt openai_segment m" in lines


def test_a_summary_that_its_rounds_do_not_give_is_named(tmp_path: Path, capsys) -> None:
    compare = script()
    path = Path(
        saved(tmp_path, "segment", [result(1, "passed", 900.0), result(2, "passed", 800.0)]).split(
            "="
        )[1]
    )
    report = json.loads(path.read_text())
    figure = report["checks"][0]["summaries"][0]["figures"][0]
    figure["median"] = 799.0  # A summary edited, or computed another way
    path.write_text(json.dumps(report))
    assert compare.main([f"segment={path}"]) == 1
    err = capsys.readouterr().err
    assert "Differs from its summary: segment voice first_text:" in err


def test_a_report_whose_summaries_do_not_cover_its_rounds_is_refused(
    tmp_path: Path, capsys
) -> None:
    compare = script()
    rounds = [result(1, "failed", 900.0, blocked_stage="stt.final"), result(2, "passed", 800.0)]
    path = Path(saved(tmp_path, "segment", rounds).split("=")[1])
    original = json.loads(path.read_text())
    assert original["checks"][0]["summaries"][0]["stopped_at"] == {"stt.final": 1}

    def refused(edit) -> str:
        report = json.loads(json.dumps(original))
        edit(report["checks"][0])
        path.write_text(json.dumps(report))
        assert compare.main([f"segment={path}"]) == 1
        return capsys.readouterr().err

    def no_summary(scenarios: dict) -> None:
        scenarios["summaries"] = []

    def twice(scenarios: dict) -> None:
        scenarios["summaries"] *= 2

    def no_figure(scenarios: dict) -> None:
        scenarios["summaries"][0]["figures"] = [
            f for f in scenarios["summaries"][0]["figures"] if f["name"] != "input"
        ]

    def stopped_elsewhere(scenarios: dict) -> None:
        scenarios["summaries"][0]["stopped_at"] = {"stt.final": 1, "turn": 1}

    assert "voice (stt openai_segment m): no summary" in refused(no_summary)
    assert "more than one summary" in refused(twice)
    assert "figures missing ['input'], not in its rounds []" in refused(no_figure)
    assert "stopped at {'stt.final': 1, 'turn': 1} != {'stt.final': 1}" in refused(
        stopped_elsewhere
    )
