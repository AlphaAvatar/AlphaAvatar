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
"""Doctor's diagnostic session over the production chain, with controlled stand-ins.

The session runs in Doctor's own diagnostic process, as it does for users; ``doctor_doubles``
stands in there for the external services and the model files only. The Router, Context,
Loop, Engine, output runtime and shared inference are production code. These tests check
correlation, timing definitions, degradation and reclamation; what a real model, STT or TTS
measures is recorded separately, in the T-10C log.
"""

from __future__ import annotations

import asyncio
import http.server
import json
import logging
import os
import re
import shutil
import signal
import socket
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import doctor_doubles as doubles
import pytest

# Imported at collection: the persona plugin's OpenCV adjusts process variables (O-2).
import alphaavatar.plugins.persona.factory  # noqa: F401
from alphaavatar.host.cli.app import main
from alphaavatar.host.cli.commands import doctor as cli_doctor
from alphaavatar.host.configs import ConfigSource, load_application
from alphaavatar.host.doctor import (
    prepare,
    process as doctor_process,
    samples,
    session as doctor_session,
)

CARD = samples.VOICE_VISION.prompt
SUM = samples.VOICE.prompt
# What the test configuration's rounds run with, vision on and off, as the report labels them.
LABEL = "model m · stt openai_segment m · tts openai m · vision vlm, max_frames 4"
BLIND = "model m · stt openai_segment m · tts openai m · vision off"
OFFLINE = ("ALPHAAVATAR_MODEL_OFFLINE", "HF_HUB_OFFLINE")


@pytest.fixture
def chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, socket_root: Path):
    """The stand-ins as the diagnostic process will install them; ``spec`` describes them."""
    files = tmp_path / "child"
    files.mkdir()
    spec = {
        "files": str(files),
        "stt": [CARD, SUM],  # The card question, then the two-sentence one
        "runners": {"voice": ["SpeechRunner"], "router": ["TurnTakingRunner"]},
    }
    monkeypatch.setattr(doctor_process, "_main", doubles.child)
    doubles.resolvable(monkeypatch)
    # Doctor's directory, the diagnostic process's temporary root, goes under a root of the
    # test's own, which must end empty.
    return SimpleNamespace(spec=spec, files=files, root=socket_root)


def configuration(tmp_path: Path, **sections: object) -> Path:
    value = {
        "application": {"home": str(tmp_path / "home")},
        "avatar": {"id": "doctor-session", "name": "Alpha"},
        "loop": {
            "plugin": "realtime",
            "init_config": {"model": {"backend": "scripted", "provider": "openai", "model": "m"}},
        },
        "voice": {
            "vad": {"plugin": "silero"},
            "stt": {"plugin": "openai_segment", "model": "m"},
            "tts": {"plugin": "openai", "model": "m", "speaker": "ash"},
        },
        "vision": {"enabled": True, "input_mode": "vlm"},
        "router": {
            "init_config": {
                "addressing": {"semantic": {"enabled": False}, "visual": {"enabled": False}}
            }
        },
        "status": {"enabled": False},
        "tools": {
            "deepresearch": {"plugin": None},
            "rag": {"plugin": None},
            "mcp": {"enabled": False},
        },
        "memory": {"plugin": "doctor"},
        "persona": {"plugin": "doctor"},
        "host": {"doctor": {"external_services": True}},
    } | sections
    path = tmp_path / "avatar.json"
    path.write_text(json.dumps(value))
    return path


def doctor(
    capsys: pytest.CaptureFixture,
    chain: SimpleNamespace,
    *argv: str,
    json_output: bool = True,
    online: bool = False,
    rounds: int = 1,
) -> tuple[int, dict[str, dict]]:
    """One run, ``rounds`` of each scenario. ``online`` lets its runners download models, as
    on a machine that does not switch downloads off; this process's environment stays as it
    was either way."""
    environ = {k: v for k, v in os.environ.items() if not online or k not in OFFLINE}
    environ[doubles.SPEC] = json.dumps(chain.spec)
    environ["COLUMNS"] = "100"  # The text as a 100-column terminal shows it.
    for name in ("requests.jsonl", "committed", "network", "runs.jsonl"):
        (chain.files / name).unlink(missing_ok=True)
    with mock.patch.dict(os.environ, environ, clear=True):
        code = main(["doctor", *argv, "--rounds", str(rounds), *["--json"] * json_output])
        assert dict(os.environ) == environ
    # The diagnostic process's own guard: nothing reached for the network, swallowed or not.
    assert not (chain.files / "network").exists()
    if not json_output:
        return code, {}
    report = json.loads(capsys.readouterr().out)
    assert code in (130, 1 if report["status"] == "FAIL" else 0)
    return code, {check["id"]: check for check in report["checks"]}


def scenarios(checks: dict[str, dict]) -> dict[tuple[str, str], dict]:
    return {(s["name"], s["configuration"]): s for s in checks["session.scenarios"]["scenarios"]}


def requests(chain: SimpleNamespace) -> list[dict]:
    lines = (chain.files / "requests.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


def test_the_configured_chain_runs_fixed_samples_and_one_request_carries_speech_and_frames(
    tmp_path: Path, chain: SimpleNamespace, capsys: pytest.CaptureFixture
) -> None:
    path = configuration(tmp_path)
    level = logging.getLogger("alphaavatar").level
    # The runtime starts as start starts it; the endpoint and the log capture stay in the
    # diagnostic process.
    _, checks = doctor(capsys, chain, str(path), online=True)
    assert logging.getLogger("alphaavatar").level == level
    assert [
        checks[c]["status"] for c in ("session.start", "models.runners", "session.cleanup")
    ] == ["PASS"] * 3
    assert {runner["method"] for runner in checks["models.runners"]["runners"]} == {
        doubles.SpeechRunner.INFERENCE_METHOD,
        doubles.TurnTakingRunner.INFERENCE_METHOD,
    }
    # Vision on: the card question alone, as agreed; the two-sentence one runs with it off.
    found = scenarios(checks)
    assert {name for name, _ in found} == {"voice_vision", "voice", "image_input", "visual_output"}
    vision = found["voice_vision", LABEL]
    assert (vision["outcome"], vision["transcript"], vision["answer"]) == ("passed", CARD, "Green.")
    assert found["voice", LABEL]["outcome"] == "not_enabled"
    assert vision["round"] == 1 and vision["sample"].startswith("card_question sha256:")
    runs = [json.loads(line) for line in (chain.files / "runs.jsonl").read_text().splitlines()]
    assert [run["tasks"] for run in runs] == [["voice_vision"]] and len(requests(chain)) == 1
    assert checks["session.start"]["metrics"][0]["samples"] == 1
    assert found["image_input", LABEL]["outcome"] == "no_coverage"
    assert found["visual_output", LABEL]["outcome"] == "not_enabled"
    assert checks["session.scenarios"]["status"] == "PASS"

    # The request itself carried this Turn's committed input and the sample's frames.
    request = vision["request"]
    assert request["carries_turn_input"] and request["frames"] == request["sample_frames"] > 0
    assert (request["attempts"], request["finals"], request["requests"]) == (1, 1, 1)
    seen = requests(chain)[0]
    assert seen["card"] and len(seen["images"]) == request["frames"]
    # Context selected them; the request carried them; all are frames Doctor published.
    assert vision["frames"] and all(
        f["published"] and f["selected"] and f["requested"] for f in vision["frames"]
    )
    assert all(item["terminal"] == "completed" for item in vision["outputs"])

    # Evidence follows the chain, joined through the trace's own identities.
    order = [item["stage"] for item in vision["evidence"]]
    chain_order = [
        "input.voiced_end",
        "perception.speech_closed",
        "stt.terminal",
        "turn.committed",
        "context.frame_selected",
        "model.request",
        "model.request_frame",
        "model.request_sent",
        "output.text_chunk",
        "output.audio_frame",
    ]
    assert sorted(map(order.index, chain_order)) == list(map(order.index, chain_order))
    # The response starts with the frame that carries the last voiced sample, 1 s in.
    at = {item["stage"]: item["at_ms"] for item in reversed(vision["evidence"])}
    assert at["input.voiced_end"] == 0
    assert at["input.audio_started"] == pytest.approx(-1000, abs=5)
    first = {item["stage"]: item["detail"] for item in reversed(vision["evidence"])}
    commit = next(
        item["detail"]
        for item in vision["evidence"]
        if item["stage"] == "input.decision" and item["detail"]["action"] == "commit"
    )
    # One segment closed, transcribed and committed; one Turn selected, requested, answered.
    assert first["perception.speech_closed"]["segment"] == first["stt.terminal"]["segment"]
    assert first["turn.committed"]["decision"] == commit["decision"]
    turn = first["turn.committed"]["turn"]
    assert {first[stage]["turn"] for stage in ("context.frame_selected", "model.request")} == {turn}
    assert first["model.request"]["input"] == first["turn.committed"]["input"]
    # The run and request of the loop's own log are the trace's; the outputs are that run's,
    # their text that request's.
    assert first["model.started"]["run"] == first["model.request"]["run"] == request["run"]
    assert first["model.started"]["request"] == first["model.request_frame"]["request"]
    assert first["model.request_sent"]["request"] == first["model.started"]["request"]
    assert first["output.audio_frame"]["run"] == request["run"]
    assert first["output.text_chunk"]["request"] == first["model.started"]["request"]
    assert {m["name"] for m in checks["models.runners"]["metrics"]} == {
        "runtime_start",
        "queue_wait_max",
        "execution_max",
    }
    # One runtime start, one sample, its time the start's own end: the cache did not grow.
    start = checks["models.runners"]["metrics"][0]
    assert (start["name"], start["note"]) == ("runtime_start", "the model cache did not grow (net)")

    # One clock: the stages add up to the first audio frame, each stage its rows.
    metrics = {m["name"]: m for m in vision["metrics"] + vision["segments"]}
    metric = {name: item["value"] for name, item in metrics.items()}
    stages = ("input", "context", "output")
    assert sum(metric[s] for s in stages) == pytest.approx(metric["first_audio_frame"], abs=0.002)
    rows = {stage: [n for n in metric if n.startswith(f"{stage}.")] for stage in stages}
    for stage in ("input", "context"):
        assert sum(metric[n] for n in rows[stage]) == pytest.approx(metric[stage], abs=0.005)
    # The stand-in TTS logs no first PCM: that node merges, its next row from the TTS request.
    pcm, audio = metrics["output.first_pcm"], metrics["output.first_audio_frame"]
    assert pcm["value"] is None and pcm["note"].startswith("merged into the next row: First PCM")
    assert (audio["start"], audio["merged"]) == ("TTS request", ["first_pcm"])
    assert metric["output.first_text_delta"] + metric["output.tts_request"] + metric[
        "output.first_audio_frame"
    ] == pytest.approx(metric["output"], abs=0.005)
    # The model's first event comes before its first text, which the Host shows after it.
    assert metric["output.first_text_delta"] - metric["model_first_event"] >= 45
    assert metric["first_text"] <= metric["text_complete"] <= metric["response_final"]
    assert metric["first_audio_frame"] <= metric["audio_last_frame"] <= metric["response_final"]
    assert metric["context_ready_wait"] is not None
    # Selected frames were in before the cutoff; nothing waited for them, so no wait is shown.
    assert metric["last_selected_frame_to_cutoff"] > 0
    for name in ("vision_wait", "first_visual_output_frame"):
        assert (metric[name], metrics[name]["samples"]) == (None, 0)
    assert metric["output_events_dropped"] == 0
    # The stand-in model logs its request sent, once, as the Responses provider does.
    assert (metric["model_request_frames"], metric["model_request_attempts"]) == (
        request["frames"],
        1,
    )

    # Each external service: configured, authorized, reached and passed, or why not known.
    services = {s["name"]: s for s in checks["services.external"]["services"]}
    assert services["speech recognition (openai_segment)"]["passed"] is True
    assert services["speech synthesis (openai)"]["passed"] is True
    assert services["model providers (scripted)"]["passed"] is True
    custom = services["custom memory 'doctor'"]
    assert (custom["reached"], custom["note"]) == (None, "external access unknown")
    assert checks["services.external"]["status"] == "PASS"

    # The text shows the scenario and its table; nothing was written outside the temporary
    # workspace. The stand-ins resolve here as installed plugins would: every check passes.
    assert doctor(capsys, chain, str(path), json_output=False)[0] == 0
    shown = capsys.readouterr().out
    rows = {tuple(line.split()[:2]): line.split()[2:] for line in shown.splitlines()}
    covers = samples.VOICE_VISION.covers.split()
    assert rows["PASS", "voice_vision"] == ["1/1", "passed", "·", *covers]
    assert rows["SKIP", "image_input"] == found["image_input", LABEL]["summary"].split()
    assert f"  With {LABEL}\n  Sample {vision['sample']}\n" in shown
    assert "— First PCM → First audio frame: from an earlier node in 1 round" in shown
    table = shown.split("\nLatency · voice_vision · 1 of 1 rounds passed\n")[1].split("\n\n")[0]
    lines = [line.rstrip() for line in table.splitlines()]
    labels = [re.split(r"\s{2,}", line.strip())[0] for line in lines[1:] if line.strip()]
    assert labels[:6] == ["End to end", *(label for _, label in cli_doctor.LATENCY)]
    assert labels[6:9] == ["Input", "Final speech → VAD close", "VAD close → Final transcript"]
    assert labels[9] == "Context" and labels[14] == "Output"
    assert labels[18:20] == [
        "First PCM → First audio frame",
        "n: later rounds that passed and observed it; the stages add up to First audio frame",
    ]
    host = next(line for line in lines if "Runtime first text" in line)
    assert re.fullmatch(r"\s+Runtime first text\s+[\d,.]+ ms\s+0\s+—\s+—", host)
    assert "--rounds 1 --json" in shown
    assert not (tmp_path / "home" / "avatars").exists()
    assert list(chain.root.iterdir()) == []

    # What was checked and authorized is what starts: the file changing in between does not
    # reach the diagnostic process, which runs the snapshot loaded first.
    diagnosis = prepare(str(path), rounds=1)
    path.write_text(json.dumps(json.loads(path.read_text()) | {"vision": {"enabled": False}}))
    environ = dict(os.environ) | {doubles.SPEC: json.dumps(chain.spec)}
    with mock.patch.dict(os.environ, environ, clear=True):
        report = asyncio.run(diagnosis.run()).to_dict()
    ran = {s["name"]: s["outcome"] for c in report["checks"] for s in c["scenarios"]}
    assert ran["voice_vision"] == "passed"  # Vision on, as loaded and checked

    # Vision off: the two-sentence question alone, both sentences heard, in one segment.
    chain.spec["stt"] = [SUM]
    _, checks = doctor(capsys, chain, str(path))
    found = scenarios(checks)
    voice = found["voice", BLIND]
    assert (voice["outcome"], voice["transcript"], voice["answer"]) == ("passed", SUM, "5.")
    assert [(x["index"], x["heard"], x["lost"]) for x in voice["sentences"]] == [
        (1, True, None),
        (2, True, None),
    ]
    assert found["voice_vision", BLIND]["outcome"] == "not_enabled"
    assert not voice["frames"] and not requests(chain)[0]["images"]


def test_what_follows_the_context_build_is_the_requests_assembly_not_the_build(
    tmp_path: Path, chain: SimpleNamespace, capsys: pytest.CaptureFixture
) -> None:
    # The real loop: the Context build returns, then the request's assembly awaits 300 ms.
    chain.spec["slow_assembly"] = 0.3
    _, checks = doctor(capsys, chain, str(configuration(tmp_path)))
    vision = scenarios(checks)["voice_vision", LABEL]
    shown = {m["name"]: m["value"] for m in (*vision["metrics"], *vision["segments"])}
    assert shown["context.request_sent"] >= 300 > shown["context.context_built"]
    # The stages still add up to the first audio frame, on one clock.
    total = shown["input"] + shown["context"] + shown["output"]
    assert total == pytest.approx(shown["first_audio_frame"], abs=0.01)
    built = [e for e in vision["evidence"] if e["stage"] == "context.built"]
    assert len(built) == 1 and built[0]["detail"]["request"] == vision["request"]["request"]


def test_a_failure_is_reported_as_it_is_and_nothing_else_is_tried(
    tmp_path: Path,
    chain: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    path = configuration(tmp_path)
    # Turns end on their own outputs here, well inside this; ending by timeout would be a stall.
    monkeypatch.setattr(doctor_session, "TURN_SECONDS", 10.0)

    def ran() -> list:
        lines = (chain.files / "runs.jsonl").read_text().splitlines()
        return [json.loads(line)["tasks"] for line in lines]

    # A model without image input: the card question stops at the model, and that is all.
    chain.spec |= {"llm": {"images": False}}
    code, checks = doctor(capsys, chain, str(path))
    found = scenarios(checks)
    original = found["voice_vision", LABEL]
    assert (original["outcome"], original["blocked_stage"], original["cause"]) == (
        "failed",
        "model.first_event",
        "ModelCapabilityError: image_input",
    )
    # Context selected the frames and the request carried them: the model refused them.
    assert original["request"]["sample_frames"] > 0
    # No other scenario, configuration or runtime: one run, one request.
    assert (ran(), len(requests(chain))) == ([["voice_vision"]], 1)
    assert found["voice", LABEL]["outcome"] == "not_enabled"
    model = next(
        s for s in checks["services.external"]["services"] if s["name"].startswith("model")
    )
    assert (model["reached"], model["passed"], model["note"]) == (
        None,
        False,
        "ModelCapabilityError: image_input",
    )
    assert code == 1 and checks["session.scenarios"]["status"] == "FAIL"
    assert doctor(capsys, chain, str(path), json_output=False)[0] == 1
    shown = capsys.readouterr().out
    assert "→ The model takes no pictures: choose one that does, or turn vision off" in shown

    # Only vision's runner cannot start: the runtime does not start, and nothing else does.
    chain.spec |= {"llm": {}, "vision_runners": ["MissingModelRunner"]}
    _, checks = doctor(capsys, chain, str(path))
    runners = {r["method"]: r["status"] for r in checks["models.runners"]["runners"]}
    assert runners[doubles.MissingModelRunner.INFERENCE_METHOD] == "FAIL"
    assert (checks["models.runners"]["status"], checks["session.start"]["status"]) == ("FAIL",) * 2
    assert scenarios(checks)["voice_vision", LABEL]["blocked_stage"] == "runners"
    assert ran() == [["voice_vision"]] and not (chain.files / "requests.jsonl").exists()

    # Two outputs; the second's speech fails after its first frame. Each output is judged:
    # one completed, one failed, so nothing records a completion; no text-only run follows.
    del chain.spec["vision_runners"]
    chain.spec |= {"llm": {"messages": 2}, "tts": {"fail_after": {"2": 1}}}
    _, checks = doctor(capsys, chain, str(path))
    original = scenarios(checks)["voice_vision", LABEL]
    assert [(o["modalities"], o["terminal"], o["reason"]) for o in original["outputs"]] == [
        ("text+audio", "completed", None),
        ("text+audio", "failed", "speech_synthesis_failed"),
    ]
    assert (original["blocked_stage"], original["cause"]) == (
        "outputs.complete",
        "speech_synthesis_failed",
    )
    metrics = {m["name"]: m for m in original["metrics"]}
    for name in ("text_complete", "audio_last_frame", "response_final"):
        assert (metrics[name]["value"], metrics[name]["samples"]) == (None, 0)
    assert metrics["first_audio_frame"]["value"] is not None
    assert (ran(), len(requests(chain))) == ([["voice_vision"]], 1)
    tts = next(
        s for s in checks["services.external"]["services"] if s["name"].startswith("speech s")
    )
    assert (tts["reached"], tts["passed"]) == (True, False)

    # The request keeps the Turn's input and the frames but not its speech: not one turn.
    chain.spec |= {"drop_speech": True, "llm": {}, "tts": {}}
    _, checks = doctor(capsys, chain, str(path))
    original = scenarios(checks)["voice_vision", LABEL]
    assert (original["outcome"], original["blocked_stage"]) == ("failed", "request.content")
    request = original["request"]
    assert request["carries_turn_input"] and request["sample_frames"] > 0
    assert not request["carries_turn_content"]
    assert "The model request does not carry this Turn's transcript" in original["details"]
    # Final transcript is the final the request carries: none, so Input and Context say so.
    stage = {m["name"]: m for m in original["segments"]}["input"]
    assert stage["note"].endswith("the first model request carries no STT final")
    del chain.spec["drop_speech"]

    # Rejected credentials are the model's failure, named as such: nothing else is tried.
    chain.spec |= {"llm": {"error": "invalid_api_key"}, "tts": {}}
    _, checks = doctor(capsys, chain, str(path))
    assert scenarios(checks)["voice_vision", LABEL]["cause"] == "ModelRequestError: invalid_api_key"
    assert ran() == [["voice_vision"]]
    # An STT that hears nothing: the scenario stops at it, and no other runs.
    chain.spec |= {"llm": {}, "stt": [""]}
    _, checks = doctor(capsys, chain, str(path))
    stopped = scenarios(checks)["voice_vision", LABEL]
    assert (stopped["outcome"], ran()) == ("failed", [["voice_vision"]])
    stt = next(
        s for s in checks["services.external"]["services"] if s["name"].startswith("speech r")
    )
    assert stt["passed"] is not True
    assert checks["session.cleanup"]["status"] == "PASS"
    assert list(chain.root.iterdir()) == []


def test_an_answer_passes_only_when_it_clearly_is_the_expected_one(
    tmp_path: Path, chain: SimpleNamespace, capsys: pytest.CaptureFixture
) -> None:
    card, total = samples.VOICE_VISION, samples.VOICE
    # The card's color, as a word or stated plainly in a short sentence.
    for answer in ("Green.", "green", '"Green"', "绿色。", "The card is green.", "It's green."):
        assert card.answered(answer), answer
    # Wrong, negated, hedged, questioning, or naming another color beside it.
    for answer in ("Red.", "Not green.", "The card is not green. It is red.", "Maybe green."):
        assert not card.answered(answer), answer
    for answer in ("Green?", "I think it is green.", "It isn't green.", "Green or blue."):
        assert not card.answered(answer), answer
    for answer in ("The card is green and white.", "I cannot tell.", "It looks green."):
        assert not card.answered(answer), answer
    for answer in ("5", "5.", "Five!", "五"):
        assert total.answered(answer), answer
    # Another number that merely contains the digit is a wrong number.
    for answer in ("15", "25.", "5.5", "-5", "It is 5.", "five or six"):
        assert not total.answered(answer), answer
    assert samples.VOICE.heard(SUM) and not samples.VOICE.heard("What is 12 plus 13?")
    # Two sentences: each is heard on its own, the second lost when only the first came.
    assert samples.VOICE.heard_sentences("What is two plus three?") == (True, False)
    # The card question is one sentence: it asks for the color, not for one word.
    assert samples.VOICE_VISION.prompt == "What color is the card on my screen?"

    # The session judges with the same rule: the spoken sum answered with the wrong number.
    blind = configuration(tmp_path, vision={"enabled": False})
    chain.spec |= {"stt": [SUM], "llm": {"answers": {"sum": "15."}}}
    _, checks = doctor(capsys, chain, str(blind))
    voice = scenarios(checks)["voice", BLIND]
    assert (voice["outcome"], voice["blocked_stage"], voice["answer"]) == (
        "failed",
        "answer",
        "15.",
    )
    assert checks["session.scenarios"]["status"] == "FAIL"

    # Without voice there is no scenario to run: nothing starts, not even a runner, and the
    # report says what is missing; at a terminal, nothing is asked.
    text_only = {
        "voice": {"vad": {"plugin": None}, "stt": {"plugin": None}, "tts": {"plugin": None}},
        "router": {"init_config": {"turn_taking": {"enabled": False}}},
    }
    path = configuration(tmp_path, **text_only)
    _, checks = doctor(capsys, chain, str(path))
    assert not (chain.files / "runs.jsonl").exists()
    start = checks["session.start"]
    assert (start["status"], start["summary"]) == (
        "SKIP",
        "Not run: Doctor has no scenario for this configuration: its scenarios are spoken, and "
        "a voice session needs voice.vad, voice.stt and voice.tts; this configuration has no "
        "voice.vad, voice.stt, voice.tts",
    )
    assert start["action"].startswith("Turn voice on (voice.vad, voice.stt and voice.tts)")
    assert scenarios(checks)["voice_vision", "model m · vision vlm, max_frames 4"]["outcome"] == (
        "conditions_unmet"
    )
    unasked = configuration(tmp_path, **text_only, host={"doctor": {"external_services": False}})
    code, questions = interactive(chain, str(unasked), "--json", answers=())
    assert (code, questions) == (0, []) and not (chain.files / "runs.jsonl").exists()
    capsys.readouterr()


def wait_for(path: Path, seconds: float = 30.0) -> None:
    deadline = time.monotonic() + seconds
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.002)
    assert path.exists(), f"{path.name} never appeared"


def reclaimed(code: int | None, checks: dict[str, dict] | None, chain: SimpleNamespace) -> str:
    """What a failed cleanup leaves to look at (O-17): the exit code, the whole cleanup check,
    and the diagnostic process group's own state, as JSON."""
    group = int((chain.files / "pid").read_text())
    try:
        os.killpg(group, 0)
        alive = True
    except ProcessLookupError:
        alive = False
    try:
        pgid: int | None = os.getpgid(group)
    except ProcessLookupError:
        pgid = None
    found = {
        "exit_code": code,
        "cleanup": (checks or {}).get("session.cleanup"),
        "group": group,
        "group_alive": alive,
        "pgid": pgid,
        "left_in_root": sorted(entry.name for entry in chain.root.iterdir()),
    }
    return json.dumps(found, default=str)


def gone(group: int) -> bool:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.killpg(group, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.01)
    return False


def test_failed_starts_timeouts_and_spent_budgets_keep_their_state_and_are_reclaimed(
    tmp_path: Path,
    chain: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    path = configuration(tmp_path)
    voice = chain.spec["runners"]
    # A runner that cannot start blocks the session, which is reported at that runner.
    voice["voice"] = ["FailingInitRunner", "SpeechRunner"]
    code, checks = doctor(capsys, chain, str(path))
    runners = {r["method"]: r["status"] for r in checks["models.runners"]["runners"]}
    assert runners["test.failing_init"] == "FAIL" and set(runners.values()) == {"FAIL", "SKIP"}
    assert checks["session.start"]["status"] == "FAIL"
    assert scenarios(checks)["voice_vision", LABEL]["outcome"] == "conditions_unmet"
    assert (code, checks["session.cleanup"]["status"]) == (1, "PASS")
    assert "private" not in json.dumps(checks)

    # A start that outlives the runtime's own initialize timeout fails there, as at start,
    # with that error; its process is reclaimed.
    voice["voice"] = ["StuckRunner", "SpeechRunner"]
    stuck = configuration(tmp_path, runtime={"inference": {"initialize_timeout": 1.0}})
    _, checks = doctor(capsys, chain, str(stuck))
    runners = {r["method"]: r for r in checks["models.runners"]["runners"]}
    assert runners["test.doctor.stuck"]["summary"] == "failed: TimeoutError"
    assert (checks["session.start"]["status"], checks["session.cleanup"]["status"]) == (
        "FAIL",
        "PASS",
    )

    # A turn still speaking at its deadline: its outputs timed out, its playback and outputs
    # end with it; the next round has a session of its own anyway.
    voice["voice"] = ["SpeechRunner"]
    chain.spec |= {"tts": {"frames": 200}, "stt": [CARD, CARD]}  # Four seconds of speech each
    monkeypatch.setattr(doctor_session, "TURN_SECONDS", 3.0)
    _, checks = doctor(capsys, chain, str(path), rounds=2)
    first, second = [r for r in checks["session.scenarios"]["scenarios"] if r["round"]]
    assert first["outcome"] == "failed" and "Ended by timeout" in first["details"]
    assert [item["terminal"] for item in first["outputs"]] == ["timed_out"]
    assert first["blocked_stage"] == "outputs.complete"
    assert {m["name"]: m["value"] for m in first["metrics"]}["response_final"] is None
    assert second["evidence"] and second["request"]["turn"] != first["request"]["turn"]
    assert checks["session.cleanup"]["status"] == "PASS"
    # The runtime and each round's session: closed, each.
    assert checks["session.cleanup"]["summary"].startswith("3 owned parts closed")

    # A spent budget starts nothing more, and says so rather than failing a runner.
    spent = doctor_session.Budget(180.0, 60.0, 0.0)
    monkeypatch.setattr(doctor_session, "budget", lambda *args: spent)
    _, checks = doctor(capsys, chain, str(path))
    assert checks["models.runners"]["summary"] == (
        "Not started: the diagnosis budget was spent before the runners started"
    )
    assert checks["session.start"]["status"] == "SKIP"
    assert scenarios(checks)["voice_vision", LABEL]["blocked_stage"] == "not run: budget exhausted"


async def test_a_step_keeps_the_state_its_wait_ended_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    doubles.resolvable(monkeypatch)
    path = configuration(tmp_path)
    config = load_application(path)
    limits = doctor_session.Budget(1.0, 1.0, 10.0)
    run = doctor_session._Run(config, ConfigSource(path), (), asyncio.Event(), limits)
    run.deadline = asyncio.get_running_loop().time() + 10
    started: list[str] = []

    async def stubborn() -> str:
        started.append("started")
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            await asyncio.sleep(0.05)
        return "late"  # Returns after all, past its deadline: still a timeout.

    assert await run._bounded(stubborn, 0.05) == ("timeout", "late")
    loop = asyncio.get_running_loop()
    loop.call_later(0.05, run.stop.set)
    assert await run._bounded(stubborn, 5.0) == ("interrupted", "late")
    assert run.interrupted
    # Asked to stop, or out of budget: the next step does not start at all.
    assert await run._bounded(stubborn, 5.0) == ("interrupted", None)
    run.stop.clear()
    run.deadline = loop.time()
    assert await run._bounded(stubborn, 5.0) == ("budget", None)
    assert started == ["started", "started"]


def test_ctrl_c_and_cancellation_end_the_diagnostic_process_and_what_it_started(
    tmp_path: Path, chain: SimpleNamespace, capsys: pytest.CaptureFixture
) -> None:
    path = configuration(tmp_path)

    # Ctrl+C during the spoken turn: the terminal's signal reaches this process alone, which
    # asks the diagnostic one to stop; it closes what runs and reports what it got.
    def interrupt() -> None:
        wait_for(chain.files / "committed")  # The spoken segment has been committed to STT.
        os.kill(os.getpid(), signal.SIGINT)

    thread = threading.Thread(target=interrupt)
    thread.start()
    try:
        code, checks = doctor(capsys, chain, str(path))
    finally:
        thread.join()
    found = scenarios(checks)
    assert code == 130
    assert found["voice_vision", LABEL]["outcome"] == "interrupted"
    assert checks["session.cleanup"]["status"] == "PASS", reclaimed(code, checks, chain)
    assert gone(int((chain.files / "pid").read_text())), reclaimed(code, checks, chain)

    # Cancelling the diagnosis itself: the process and its runners go before it returns.
    async def cancelled() -> None:
        diagnosis = prepare(str(path), rounds=1)
        task = asyncio.create_task(diagnosis.run())
        await asyncio.to_thread(wait_for, chain.files / "committed")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    (chain.files / "committed").unlink()
    environ = dict(os.environ) | {doubles.SPEC: json.dumps(chain.spec)}
    with mock.patch.dict(os.environ, environ, clear=True):
        asyncio.run(cancelled())
        assert dict(os.environ) == environ
    assert gone(int((chain.files / "pid").read_text())), reclaimed(None, None, chain)
    assert list(chain.root.iterdir()) == [], reclaimed(None, None, chain)


def test_a_diagnostic_process_that_does_not_stop_is_ended_with_its_group(
    tmp_path: Path,
    chain: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    path = configuration(tmp_path)
    # It ignores both the stop and its budget, with a runner whose start never ends.
    chain.spec |= {"deaf": True, "runners": {"voice": ["StuckRunner"]}}
    sockets = {*Path("/tmp").glob("alphaavatar-inference-*")}
    short = doctor_session.Budget(1.0, 1.0, 2.0, 1.0)
    monkeypatch.setattr(doctor_session, "budget", lambda *args: short)
    monkeypatch.setattr(doctor_process, "CLOSE_SECONDS", 1.0)
    began = time.monotonic()
    code, checks = doctor(capsys, chain, str(path))
    assert time.monotonic() - began < 15
    assert code == 1
    cleanup = checks["session.cleanup"]
    assert cleanup["status"] == "FAIL"
    assert "the diagnostic process did not exit within 1 s: killed" in cleanup["details"]
    # Killed: whatever it printed last is not why it ended.
    assert checks["session.start"]["details"] == ["the diagnostic process exited with code -9"]
    assert gone(int((chain.files / "pid").read_text()))
    with pytest.raises(ProcessLookupError):  # Its runner went with its group.
        os.kill(int((chain.files / "stuck").read_text()), 0)
    # Its runtime's socket was under Doctor's directory, removed with it, not left in /tmp.
    assert list(chain.root.iterdir()) == []
    assert {*Path("/tmp").glob("alphaavatar-inference-*")} <= sockets


def test_a_diagnostic_process_that_dies_on_its_own_is_named_by_its_last_line(
    tmp_path: Path, chain: SimpleNamespace, capfd: pytest.CaptureFixture
) -> None:
    chain.spec["crash"] = True
    code, checks = doctor(capfd, chain, str(configuration(tmp_path)))
    assert code == 1
    # Its traceback went to its own file: the last line, where it ends, says why.
    why = "the diagnostic process exited with code 1: RuntimeError: stand-in session crashed"
    assert checks["session.start"]["details"] == [why]
    assert checks["session.cleanup"]["status"] == "SKIP"
    assert list(chain.root.iterdir()) == []


@pytest.fixture
def provider(socket_root: Path):
    """An HTTP stand-in for the OpenAI API on loopback: it refuses every request, and keeps
    the size of each body it received."""
    refusal = {"status": 401, "first": []}  # ``first``: statuses for the first requests
    sizes: list[int] = []

    class Refuse(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            sizes.append(len(self.rfile.read(length)))
            body = json.dumps({"error": {"message": "refused", "type": "invalid_request_error"}})
            self.send_response(refusal["first"].pop(0) if refusal["first"] else refusal["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Refuse)
    thread = threading.Thread(target=server.serve_forever, name="openai_stand_in")
    thread.start()
    try:
        yield SimpleNamespace(port=server.server_address[1], refusal=refusal, sizes=sizes)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_the_openai_adapter_refuses_pictures_as_such_and_other_refusals_keep_their_class(
    tmp_path: Path,
    chain: SimpleNamespace,
    provider: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    monkeypatch.setattr(doctor_session, "TURN_SECONDS", 10.0)
    url = f"http://127.0.0.1:{provider.port}/v1"
    model = {"backend": "openai", "provider": "openai", "model": "m"}
    model["extra"] = {"api_key": "sk-doctor-stand-in", "base_url": url}
    chain.spec |= {"loopback": provider.port}
    # The real Responses adapter cannot inline frames this large: it refuses the pictures
    # itself, before any call, and nothing else is tried.
    small = model | {"input_options": {"max_inline_bytes": 1024}}
    loop = {"plugin": "realtime", "init_config": {"model": small}}
    _, checks = doctor(capsys, chain, str(configuration(tmp_path, loop=loop)))
    found = scenarios(checks)
    vision = found["voice_vision", LABEL]
    assert vision["cause"] == "ModelCapabilityError: image_input"
    # Refused before a call: no request went out, and the figures say no more than that.
    sent = {m["name"]: m for m in vision["segments"]}
    assert sent["model_request_bytes"]["value"] is None and provider.sizes == []
    assert sent["context"]["note"].endswith("its provider logs no request sent")

    # Vision off: the spoken turn's request goes out, is refused once in transit and retried,
    # then refused by the service. Its provider logged each attempt as it went to the
    # transport, in numbers alone: the body as sent, no picture in it, encoded here once.
    provider.refusal["first"] = [500]
    retried = model | {"extra": model["extra"] | {"max_retries": 1}}
    loop = {"plugin": "realtime", "init_config": {"model": retried}}
    chain.spec["stt"] = [SUM]
    blind = configuration(tmp_path, loop=loop, vision={"enabled": False})
    _, checks = doctor(capsys, chain, str(blind))
    voice = scenarios(checks)["voice", BLIND]
    assert voice["cause"] == "ModelRequestError: http_401"
    sent = {m["name"]: m["value"] for m in voice["segments"]}
    assert sent["model_request_frames"] == 0 and sent["model_request_encode"] >= 0
    # From the request taken to its first attempt sent: the client made ready and the
    # encoding are parts of it (O-15).
    assert sent["model_request_client"] >= 0
    assert (
        sent["model_request_prepare"] >= sent["model_request_client"] + sent["model_request_encode"]
    )
    assert sent["model_request_bytes"] == provider.sizes[0] == provider.sizes[1] > 0
    assert sent["model_request_attempts"] == 2 and voice["request"]["attempts"] == 2
    attempts = [e for e in voice["evidence"] if e["stage"] == "model.request_sent"]
    assert [e["detail"]["attempt"] for e in attempts] == [1, 2]
    # Model request sent is the first attempt, before the service answered: Context ends there.
    assert sent["context"] is not None and sent["context.request_sent"] is not None
    assert attempts[0]["at_ms"] <= attempts[1]["at_ms"]

    # A generic HTTP 400 for the request with pictures is the service's, as classified.
    provider.refusal["status"] = 400
    chain.spec["stt"] = [CARD]
    loop = {"plugin": "realtime", "init_config": {"model": model}}
    _, checks = doctor(capsys, chain, str(configuration(tmp_path, loop=loop)))
    found = scenarios(checks)
    assert found["voice_vision", LABEL]["cause"] == "ModelRequestError: http_400"
    assert checks["session.cleanup"]["status"] == "PASS"


def test_the_diagnostic_process_leaves_a_calling_host_and_its_terminal_alone(
    tmp_path: Path, chain: SimpleNamespace, capfd: pytest.CaptureFixture
) -> None:
    from alphaavatar.agents.runtime.inference.bootstrap import INFERENCE_PLAN_ENV
    from alphaavatar.agents.runtime.inference.protocol import INFERENCE_ENDPOINT_ENV
    from alphaavatar.core.log.records import LOG_ENDPOINT_ENV

    # Doctor run from inside a Host: its runtime endpoint, plan and log receiver are set.
    receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    receiver.bind(str(chain.root / "host-log.sock"))
    receiver.setblocking(False)
    log = {
        "path": str(chain.root / "host-log.sock"),
        "token": "0" * 64,
        "level": 10,
        "third_party_level": 10,
        "conversation": None,
    }
    host = {
        INFERENCE_ENDPOINT_ENV: str(chain.root / "host-inference.sock"),
        INFERENCE_PLAN_ENV: "[]",
        LOG_ENDPOINT_ENV: json.dumps(log),
    }
    # The stand-ins print, in the diagnostic process and in a runner of it.
    environ = dict(os.environ) | host | {doubles.SPEC: json.dumps(chain.spec | {"stdout": True})}
    try:
        with mock.patch.dict(os.environ, environ, clear=True):
            main(["doctor", str(configuration(tmp_path)), "--json", "--rounds", "1"])
            assert dict(os.environ) == environ
        out, err = capfd.readouterr()
        checks = {check["id"]: check for check in json.loads(out)["checks"]}  # Only the report.
        # What it and its runner printed went to its own file, not stderr either.
        assert "stand-in" not in out + err
        assert [checks[c]["status"] for c in ("session.start", "models.runners")] == ["PASS"] * 2
        assert scenarios(checks)["voice_vision", LABEL]["outcome"] == "passed"
        with pytest.raises(BlockingIOError):  # Nothing of it reached the Host's receiver.
            receiver.recv(65536)
    finally:
        receiver.close()
        (chain.root / "host-log.sock").unlink()


def asked(*answers: str | BaseException):
    """A terminal: input() answering in order, or raising, and recording each question, as it
    shows them."""
    questions: list[str] = []
    queue = list(answers)

    def answer(prompt: str = "") -> str:
        questions.append(prompt)
        sys.stdout.write(prompt)  # As input() shows its prompt.
        if isinstance(reply := queue.pop(0), BaseException):
            raise reply
        return reply

    return questions, answer


def interactive(
    chain: SimpleNamespace,
    *argv: str,
    answers: tuple[str | BaseException, ...],
    online: bool = False,
    rounds: int = 1,
):
    """One run at a terminal; its exit code and the questions asked. ``online`` lets its
    runners download, as a person's own environment would."""
    questions, answer = asked(*answers)
    environ = {k: v for k, v in os.environ.items() if not online or k not in OFFLINE}
    environ |= {doubles.SPEC: json.dumps(chain.spec), "COLUMNS": "1000"}
    for name in ("requests.jsonl", "committed", "network", "runs.jsonl"):
        (chain.files / name).unlink(missing_ok=True)
    with (
        mock.patch.dict(os.environ, environ, clear=True),
        mock.patch("sys.stdin.isatty", return_value=True),
        mock.patch("builtins.input", answer),
    ):
        code = main(["doctor", *argv, "--rounds", str(rounds)])
    assert not (chain.files / "network").exists()
    return code, questions


@pytest.mark.parametrize("agreed", [True, False], ids=["agreed", "declined"])
def test_the_diagnosis_runs_only_once_a_person_agrees_to_all_it_does(
    tmp_path: Path, chain: SimpleNamespace, capsys: pytest.CaptureFixture, agreed: bool
) -> None:
    # Not authorized by the configuration: a person at the terminal decides.
    path = configuration(tmp_path, host={"doctor": {"external_services": False}})
    code, questions = interactive(chain, str(path), "--json", answers=("y" if agreed else "",))
    output = capsys.readouterr()
    report = json.loads(output.out)  # Asked on stderr: stdout is the JSON alone.
    checks = {check["id"]: check for check in report["checks"]}
    assert questions == [""] and "    Run the diagnosis? [y/N]: " in output.err
    # Before the one question: each scenario and its rounds, the downloads it may make, each
    # service it calls, and that the calls may be billed.
    assert "then runs this scenario once, each time in a session of its own:" in output.err
    assert re.search(rf"\n    voice_vision +{samples.VOICE_VISION.covers}\n", output.err)
    assert "\n    voice " not in output.err and "\n    text " not in output.err
    assert "Model files the cache lacks are downloaded first, as start would." in output.err
    for name in ("model providers (scripted)", "speech recognition (openai_segment)"):
        assert f"    {name}\n" in output.err
    assert "Calls to these services may be billed." in output.err
    found = scenarios(checks)
    if agreed:
        assert code == 0 and found["voice_vision", LABEL]["outcome"] == "passed"
        assert checks["services.external"]["services"][0]["authorized"] is True
    else:
        assert code == 0 and not (chain.files / "requests.jsonl").exists()  # Nothing ran.
        for check in ("session.start", "models.runners", "session.scenarios"):
            assert (checks[check]["status"], checks[check]["summary"]) == (
                "SKIP",
                "Not run: the diagnosis was declined",
            )
    assert list(chain.root.iterdir()) == []


def test_ctrl_c_at_the_question_runs_nothing_and_says_so(
    tmp_path: Path, chain: SimpleNamespace, capsys: pytest.CaptureFixture
) -> None:
    path = configuration(tmp_path, host={"doctor": {"external_services": False}})
    code, _ = interactive(chain, str(path), answers=(KeyboardInterrupt(),))
    shown = capsys.readouterr().out
    assert code == 130 and not (chain.files / "requests.jsonl").exists()
    # The question's line ends, then a blank line: the report stands apart from it.
    assert "    Run the diagnosis? [y/N]: \n\n" in shown
    lines = shown.splitlines()
    start = lines.index("  SKIP  Session and services")
    assert lines[start + 1] == "        Not run: interrupted at a question"
    assert list(chain.root.iterdir()) == []


def test_no_metrics_leaves_the_diagnosis_out_without_asking(
    tmp_path: Path, chain: SimpleNamespace, capsys: pytest.CaptureFixture
) -> None:
    path = configuration(tmp_path, host={"doctor": {"external_services": False}})
    code, questions = interactive(chain, str(path), "--no-metrics", answers=())
    shown = capsys.readouterr().out
    assert (code, questions) == (0, []) and not (chain.files / "requests.jsonl").exists()
    lines = shown.splitlines()
    start = lines.index("  SKIP  Session and services")
    assert lines[start + 1] == "        Not run: left out with --no-metrics"
    assert "  Not measured · Not run: left out with --no-metrics" in lines


def reference_run(tmp_path: Path, statuses) -> tuple[object, frozenset[str]]:
    """The reference bundle's diagnostic run, its runners as ``statuses`` has them: by
    whether each embeds as it starts, as a vector store's does."""
    from alphaavatar.agents.runtime.inference import plan_inference_runners
    from alphaavatar.host.configs.paths import ApplicationPaths
    from alphaavatar.host.configs.template import create_bundle
    from alphaavatar.host.doctor import CheckStatus
    from alphaavatar.host.doctor.schemas.session import RunnerResult

    paths = ApplicationPaths.from_root(tmp_path / "home")
    create_bundle(paths, "ref", avatar_id="ref")
    source = ConfigSource(paths.configs.bundles_dir / "ref.yaml", "ref", home=paths.root)
    config = load_application(source)
    embedding = doctor_session.embedding_runners(config)
    planned = list(plan_inference_runners(config.avatar))
    assert embedding and set(planned) - embedding  # Both kinds, without naming either.
    run = doctor_session._Run(config, source, [], asyncio.Event(), doctor_session.budget())
    run.runners = [
        RunnerResult(m, CheckStatus(statuses[m in embedding]), "", startup_seconds=1.0)
        for m in planned
    ]
    return run, embedding


# What a vector store's start failure shows: its probe's own error, or one before it.
PROBE = ("error: RuntimeError", "error: EmbeddingProbeError", "error: AuthenticationError")
OPENING = ("error: RuntimeError", "error: OSError", "at lancedb:1 in connect")


@pytest.mark.parametrize(
    ("statuses", "error", "expected", "note"),
    [
        # An earlier runner failed: the vector stores never started, nor embedded.
        (
            {False: "FAIL", True: "SKIP"},
            (),
            (None, None),
            "vector store embeddings: an earlier runner did not start",
        ),
        ({False: "PASS", True: "PASS"}, (), (True, True), "vector store embeddings"),
        # Only the probe's own failure is the provider's.
        ({False: "PASS", True: "FAIL"}, PROBE, (None, False), "the embedding probe failed"),
        # A store that failed to open never sent it: the runner failed, the provider unseen.
        ({False: "PASS", True: "FAIL"}, OPENING, (None, None), "failed before its probe"),
    ],
    ids=["not reached", "started", "probe failed", "failed before the probe"],
)
def test_the_model_provider_is_judged_by_the_probe_of_the_runners_that_embed(
    tmp_path: Path, statuses: dict[bool, str], error: tuple, expected: tuple, note: str
) -> None:
    run, _ = reference_run(tmp_path, statuses)
    run.runner_error = error
    result = run._service("model providers (openai)", "model", True, ())
    assert (result.reached, result.passed) == expected
    assert note in result.note


THIRD_PARTY = Path(__file__).parents[1] / "fixtures" / "thirdparty"


@pytest.mark.parametrize("asked", [None, "n", "y"], ids=["unattended", "declined", "agreed"])
def test_nothing_starts_before_the_diagnosis_is_agreed_to_not_even_a_runner(
    tmp_path: Path,
    chain: SimpleNamespace,
    capfd: pytest.CaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    asked: str | None,
) -> None:
    from alphaavatar.agents.runtime.plugin import AvatarModule

    monkeypatch.syspath_prepend(str(THIRD_PARTY))  # This process, and those it spawns
    from alphaavatar.plugins.doctor_thirdparty.runner import ThirdPartyRunner

    # Planned by the persona the configuration names, here and in the diagnostic process.
    persona = doubles.stand_in(
        AvatarModule.PERSONA, "doctor", object, lambda c: (ThirdPartyRunner,)
    )
    monkeypatch.setitem(doubles.resolution._resolved, (AvatarModule.PERSONA, "doctor"), persona)
    chain.spec["vision_runners"] = ["alphaavatar.plugins.doctor_thirdparty.runner:ThirdPartyRunner"]
    path = configuration(tmp_path, host={"doctor": {"external_services": False}})
    if asked is None:
        _, checks = doctor(capfd, chain, str(path))
        err = ""
    else:
        _, questions = interactive(chain, str(path), "--json", answers=(asked,))
        out, err = capfd.readouterr()
        checks = {check["id"]: check for check in json.loads(out)["checks"]}
        assert questions == [""]  # Asked on stderr: stdout is the JSON alone.
        assert "    Run the diagnosis? [y/N]: " in err
    # A runner of any package, one in the plugins' own namespace too: its start runs only in
    # a diagnosis agreed to, or authorized.
    started = (chain.files / "thirdparty").exists()
    assert started == (asked == "y")
    if not started:
        assert checks["models.runners"]["status"] == "SKIP"
    assert list(chain.root.iterdir()) == []


def test_a_missing_file_is_the_runners_failure_reported_as_it_is(
    tmp_path: Path, chain: SimpleNamespace, capfd: pytest.CaptureFixture
) -> None:
    chain.spec["runners"] = {"voice": ["SpeechRunner"], "router": ["MissingFileRunner"]}
    # Authorized, at a terminal: the start's own failure, its error and where it was raised.
    code, questions = interactive(
        chain, str(configuration(tmp_path)), "--json", answers=(), online=True
    )
    out, _ = capfd.readouterr()
    checks = {check["id"]: check for check in json.loads(out)["checks"]}
    assert code == 1 and questions == []
    runs = [json.loads(line) for line in (chain.files / "runs.jsonl").read_text().splitlines()]
    # One start, past its two runners' own initialize timeouts: theirs is what fails first.
    assert runs == [{"rounds": 1, "runners": 2 * 300.0 + 30.0, "tasks": ["voice_vision"]}]
    runners = checks["models.runners"]
    assert "not in the cache" not in runners["summary"]
    assert "error: FileNotFoundError" in runners["details"]
    assert any("in initialize" in line for line in runners["details"])  # Where it was raised
    assert runners["action"].startswith("Fix what the error names")


def test_the_input_ending_at_the_question_declines_and_the_report_follows(
    tmp_path: Path, chain: SimpleNamespace, capfd: pytest.CaptureFixture
) -> None:
    path = configuration(tmp_path, host={"doctor": {"external_services": False}})
    code, questions = interactive(chain, str(path), "--json", answers=(EOFError(),))
    out, _ = capfd.readouterr()
    checks = {check["id"]: check for check in json.loads(out)["checks"]}
    assert questions == [""] and code == 0
    assert checks["session.start"]["summary"] == "Not run: the diagnosis was declined"
    assert not (chain.files / "requests.jsonl").exists()


def wait_lines(path: Path, count: int, seconds: float = 60.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists() and len(path.read_text().splitlines()) >= count:
            return
        time.sleep(0.005)
    raise AssertionError(f"{path.name} never had {count} lines")


def test_the_scenario_runs_in_rounds_each_in_a_session_and_the_rounds_are_summarized(
    tmp_path: Path, chain: SimpleNamespace, capsys: pytest.CaptureFixture
) -> None:
    import statistics

    # Round 2 of the two-sentence question loses its second sentence in STT; the rest pass.
    chain.spec["stt"] = [SUM, "What is two plus three?", SUM]
    blind = configuration(tmp_path, vision={"enabled": False})
    code, checks = doctor(capsys, chain, str(blind), rounds=3)
    assert code == 1 and checks["session.scenarios"]["status"] == "FAIL"
    (voice,) = checks["session.scenarios"]["summaries"]
    assert (voice["name"], voice["configuration"]) == ("voice", BLIND)
    assert (voice["rounds"], voice["passed"], voice["stopped_at"]) == (3, 2, {"stt.final": 1})
    # The failed round: the sentence it lost, each layer's evidence, the layer that lost it.
    rounds = [r for r in checks["session.scenarios"]["scenarios"] if r["round"]]
    failed = [r for r in rounds if r["outcome"] == "failed"]
    assert [r["round"] for r in failed] == [2]
    (second,) = [s for s in failed[0]["sentences"] if not s["heard"]]
    assert (second["coverage"], second["stt"], second["adopted"], second["content"]) == (
        "full",
        "final",
        True,
        "lacks_its_words",
    )
    assert second["lost"] == "stt" and "holds another sentence too" in second["why"]
    # Each figure over the passed rounds: the first round apart, then the later ones.
    values = {
        r["round"]: {m["name"]: m["value"] for m in r["metrics"]}["first_text"] for r in rounds
    }
    figure = {f["name"]: f for f in voice["figures"]}["first_text"]
    assert (figure["first"], figure["samples"], figure["median"]) == (values[1], 1, values[3])
    assert figure["p95"] is None
    # Every round observed it, the failed one too: apart, and said so.
    later = sorted((values[2], values[3]))
    assert (figure["all_first"], figure["all_samples"]) == (values[1], 2)
    assert (figure["all_median"], figure["all_low"], figure["all_high"]) == (
        round(statistics.median(later), 3),
        later[0],
        later[1],
    )
    # One runtime start for every round; a session for each of the three.
    starts = [m for m in checks["models.runners"]["metrics"] if m["name"] == "runtime_start"]
    assert len(starts) == 1 and checks["session.start"]["metrics"][0]["samples"] == 3
    assert checks["session.cleanup"]["status"] == "PASS"
    assert list(chain.root.iterdir()) == []


def test_the_text_shows_the_figures_the_json_holds(
    tmp_path: Path, chain: SimpleNamespace, capsys: pytest.CaptureFixture
) -> None:
    """One report, as text and as JSON: each row's Round 1, n, median and range, the passed
    rounds' and every round's, are the same numbers."""
    from alphaavatar.host.cli.render import Report

    chain.spec["stt"] = [SUM, "What is two plus three?", SUM]
    path = configuration(tmp_path, vision={"enabled": False})
    environ = dict(os.environ) | {doubles.SPEC: json.dumps(chain.spec), "COLUMNS": "100"}
    with mock.patch.dict(os.environ, environ, clear=True):
        diagnosis = prepare(str(path), rounds=3)
        report = asyncio.run(diagnosis.run())
        cli_doctor._text(Report(), report, diagnosis, str(path), False, False)
    shown = capsys.readouterr().out
    data = {check["id"]: check for check in report.to_dict()["checks"]}
    (summary,) = data["session.scenarios"]["summaries"]
    tables = dict(
        part.split("\n\n")[0].split("\n", 1) for part in shown.split("\nLatency · voice · ")[1:]
    )
    passed, every = "2 of 3 rounds passed", "every round, the 1 not passed included"
    assert set(tables) == {passed, every}
    labels = dict(cli_doctor.LATENCY)
    for stage, title, rows in cli_doctor._stages():
        labels |= {stage: title, **dict(rows)}
    for title, prefix in ((passed, ""), (every, "all_")):
        cells = {}
        for line in tables[title].splitlines()[1:]:
            label, *values = re.split(r"\s{2,}", line.strip())
            cells[label] = values
        for figure in summary["figures"]:
            if figure["name"] not in labels:
                continue
            n, unit = figure[f"{prefix}samples"], figure["unit"]
            low, high = figure[f"{prefix}low"], figure[f"{prefix}high"]
            expected = [
                cli_doctor._in(unit, figure[f"{prefix}first"]),
                str(n),
                cli_doctor._in(unit, figure[f"{prefix}median"]),
                cli_doctor._range(unit, low, high) if n else "—",
            ]
            assert cells[labels[figure["name"]]] == expected, (title, figure["name"])


def test_model_files_load_from_the_cache_and_one_missing_downloads_as_start_does(
    tmp_path: Path, chain: SimpleNamespace, capsys: pytest.CaptureFixture
) -> None:
    chain.spec["runners"] = {"voice": ["SpeechRunner"], "router": ["CachedModelRunner"]}
    path = configuration(tmp_path)

    def start(checks: dict) -> dict:
        return next(m for m in checks["models.runners"]["metrics"] if m["name"] == "runtime_start")

    # A first start: the weights are not in the cache, so it fetches them as start would,
    # and its one start sample says so.
    _, checks = doctor(capsys, chain, str(path), online=True)
    assert checks["session.start"]["status"] == "PASS"
    assert start(checks)["note"] == "the model cache grew by 64.0 KB (net)"
    assert (chain.files / "model.log").read_text().splitlines() == ["download"]
    # The next start loads them: the cache does not grow. Its time ends with the start, not
    # with the scan of the cache that follows it, however slow.
    chain.spec["slow_scan"] = 2.0
    _, checks = doctor(capsys, chain, str(path), online=True)
    assert start(checks)["note"] == "the model cache did not grow (net)"
    assert start(checks)["value"] < 2000
    del chain.spec["slow_scan"]
    assert (chain.files / "model.log").read_text().splitlines() == ["download", "cache"]
    # A start that fetches them again over the ones there: no net growth, and no claim that
    # nothing was fetched; a cache scan tells no download apart.
    chain.spec["refetch"] = True
    _, checks = doctor(capsys, chain, str(path), online=True)
    assert start(checks)["note"] == "the model cache did not grow (net)"
    fetched = (chain.files / "model.log").read_text().splitlines()
    assert fetched == ["download", "cache", "download"]
    del chain.spec["refetch"]
    # This machine switches downloads off: the start fails as start's would, and says how.
    shutil.rmtree(tmp_path / "home" / "cache" / "models" / "doctor")
    with mock.patch.dict(os.environ, {"ALPHAAVATAR_MODEL_OFFLINE": "1"}):
        code, checks = doctor(capsys, chain, str(path))
    runners = checks["models.runners"]
    assert code == 1 and runners["status"] == "FAIL"
    assert runners["summary"].endswith(
        "did not start: its model is not in the cache; 0 not reached"
    )
    assert runners["action"].startswith("Model downloads are switched off here")
    assert list(chain.root.iterdir()) == []


def test_ctrl_c_in_a_later_round_keeps_what_ran_and_reclaims_everything(
    tmp_path: Path, chain: SimpleNamespace, capsys: pytest.CaptureFixture
) -> None:
    chain.spec["stt"] = [CARD, CARD, CARD]

    def interrupt() -> None:
        # The first round's spoken segment, then the second round's.
        wait_lines(chain.files / "committed", 2)
        os.kill(os.getpid(), signal.SIGINT)

    thread = threading.Thread(target=interrupt)
    thread.start()
    try:
        code, checks = doctor(capsys, chain, str(configuration(tmp_path)), rounds=3)
    finally:
        thread.join()
    assert code == 130
    rounds = {
        (r["name"], r["round"]): r["outcome"]
        for r in checks["session.scenarios"]["scenarios"]
        if r["round"]
    }
    # Round 1 ran whole; round 2 stopped in its turn, and round 3 did not run.
    assert [rounds["voice_vision", at] for at in (1, 2, 3)] == ["passed"] + ["interrupted"] * 2
    (summary,) = checks["session.scenarios"]["summaries"]
    assert (summary["passed"], summary["rounds"]) == (1, 3)
    assert checks["session.cleanup"]["status"] == "PASS", reclaimed(code, checks, chain)
    assert gone(int((chain.files / "pid").read_text())), reclaimed(code, checks, chain)
    assert list(chain.root.iterdir()) == [], reclaimed(code, checks, chain)
