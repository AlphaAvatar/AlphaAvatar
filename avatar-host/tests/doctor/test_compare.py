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
"""``scripts/quality/doctor_compare.py``: Doctor's JSON reports side by side."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).parents[3] / "scripts" / "quality" / "doctor_compare.py"


def report(passed: int, stopped: dict[str, int], median: float, lost: str | None) -> dict:
    figure = {"name": "stt_final", "unit": "ms", "first": 900.0, "samples": 4, "median": median}
    encode = {"name": "model_request_encode", "unit": "ms", "first": 0.223, "samples": 4}
    rounds = [
        {
            "name": "voice",
            "round": 2,
            "evidence": [{"stage": "candidate.decision", "detail": {"action": "cancel"}}],
            "sentences": [{"index": 2, "heard": lost is None, "lost": lost}],
        }
    ]
    summary = {"name": "voice", "configuration": "original", "rounds": 5, "passed": passed}
    summary |= {"stopped_at": stopped, "figures": [figure, encode | {"median": 0.106}]}
    scenarios = {"id": "session.scenarios", "summaries": [summary], "scenarios": rounds}
    return {"status": "PASS", "checks": [scenarios]}


def test_reports_compare_by_scenario_figure_and_turn_taking(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("doctor_compare", SCRIPT)
    compare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(compare)
    paths = []
    for name, data in (
        ("segment", report(4, {"stt.final": 1}, 2459.0, "stt")),
        ("realtime", report(5, {}, 812.0, None)),
    ):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(data))
        paths.append(f"{name}={path}")
    lines = compare.compare([(arg.split("=")[0], compare.load(arg.split("=")[1])) for arg in paths])
    rows = {line.split("  ")[0].strip(): line.split()[-2:] for line in lines[2:] if line}
    assert lines[1].split() == ["segment", "realtime"]
    assert rows["Rounds passed"][-1] == "5/5" and "4/5; 1 at stt.final" in lines[2]
    assert "2,459 (900)" in lines[3] and "812 (900)" in lines[3]
    assert rows["Request encoding"] == ["0.1", "(0.2)"]
    assert rows["Cancels"] == ["1", "1"] and rows["Sentences lost in stt"] == ["1", "0"]
