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
import signal
import socket
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import doctor_doubles as doubles
import pytest

# Imported at collection: configuration plugins adjust process variables while importing (O-2).
import alphaavatar.agents.configs  # noqa: F401
from alphaavatar.host.cli.app import main
from alphaavatar.host.configs import ConfigSource, load_application
from alphaavatar.host.doctor import (
    prepare,
    process as doctor_process,
    samples,
    session as doctor_session,
)

CARD = samples.VOICE_VISION.prompt
SUM = samples.VOICE.prompt
OFFLINE = ("ALPHAAVATAR_MODEL_OFFLINE", "HF_HUB_OFFLINE")


@pytest.fixture
def chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, socket_root: Path):
    """The stand-ins as the diagnostic process will install them; ``spec`` describes them."""
    files = tmp_path / "child"
    files.mkdir()
    spec = {
        "files": str(files),
        "stt": [CARD],
        "runners": {"voice": ["SpeechRunner"], "router": ["EndpointRunner"]},
    }
    monkeypatch.setattr(doctor_process, "_main", doubles.child)
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
) -> tuple[int, dict[str, dict]]:
    """One run. ``online`` lets this process download models: only the diagnostic process
    and its runners switch that off, and this process's environment stays as it was."""
    environ = {k: v for k, v in os.environ.items() if not online or k not in OFFLINE}
    environ[doubles.SPEC] = json.dumps(chain.spec)
    for name in ("requests.jsonl", "committed", "network"):
        (chain.files / name).unlink(missing_ok=True)
    with mock.patch.dict(os.environ, environ, clear=True):
        code = main(["doctor", *argv, *["--json"] * json_output])
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
    # The runners still start offline, the stand-in turn-taking one only so; the endpoint,
    # the offline switch and the log capture stay in the diagnostic process.
    _, checks = doctor(capsys, chain, str(path), online=True)
    assert logging.getLogger("alphaavatar").level == level
    assert [
        checks[c]["status"] for c in ("session.start", "models.runners", "session.cleanup")
    ] == ["PASS"] * 3
    assert {runner["method"] for runner in checks["models.runners"]["runners"]} == {
        doubles.SpeechRunner.INFERENCE_METHOD,
        doubles.EndpointRunner.INFERENCE_METHOD,
    }
    found = scenarios(checks)
    vision, text = found["voice_vision", "original"], found["text", "original"]
    assert (vision["outcome"], text["outcome"]) == ("passed", "passed")
    assert (vision["transcript"], vision["answer"], text["answer"]) == (CARD, "Green.", "5.")
    assert found["image_input", "original"]["outcome"] == "no_coverage"
    assert found["visual_output", "original"]["outcome"] == "not_enabled"
    assert checks["session.scenarios"]["status"] == "PASS"

    # The request itself carried this Turn's committed input and the sample's frames.
    request = vision["request"]
    assert request["carries_turn_input"] and request["frames"] == request["sample_frames"] > 0
    seen = requests(chain)[0]
    assert seen["card"] and len(seen["images"]) == request["frames"]
    # Context selected them; the request carried them; all are frames Doctor published.
    assert vision["frames"] and all(
        f["published"] and f["selected"] and f["requested"] for f in vision["frames"]
    )
    assert all(item["terminal"] == "completed" for item in vision["outputs"] + text["outputs"])

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
        if item["stage"] == "candidate.decision" and item["detail"]["action"] == "commit"
    )
    # One segment closed, transcribed and committed; one Turn selected, requested, answered.
    assert first["perception.speech_closed"]["segment"] == first["stt.terminal"]["segment"]
    assert first["turn.committed"]["decision"] == commit["decision"]
    turn = first["turn.committed"]["turn"]
    assert {first[stage]["turn"] for stage in ("context.frame_selected", "model.request")} == {turn}
    assert first["model.request"]["input"] == first["turn.committed"]["input"]
    # The run and request of the loop's own log are the trace's; the outputs are that run's.
    assert first["model.started"]["run"] == first["model.request"]["run"] == request["run"]
    assert first["model.started"]["request"] == first["model.request_frame"]["request"]
    assert first["output.audio_frame"]["run"] == request["run"]
    assert {m["name"] for m in checks["models.runners"]["metrics"]} == {
        "queue_wait_max",
        "execution_max",
    }

    # One clock: the segments add up to the end-to-end figure they divide.
    metrics = {m["name"]: m for m in vision["metrics"] + vision["segments"]}
    metric = {name: item["value"] for name, item in metrics.items()}
    parts_sum = (
        metric["turn_cutoff"] + metric["cutoff_to_model_request"] + metric["first_displayable_text"]
    )
    assert parts_sum == pytest.approx(metric["first_text"], abs=0.01)
    assert metric["vad_close"] <= metric["stt_final"] <= metric["turn_cutoff"]
    # The first stream event, the first text delta and the first text out are each timed.
    assert metric["model_first_text_delta"] - metric["model_first_event"] >= 45
    assert metric["model_first_text_delta"] <= metric["first_displayable_text"]
    assert metric["first_text"] <= metric["text_complete"] <= metric["response_final"]
    assert metric["first_audio_frame"] <= metric["audio_last_frame"] <= metric["response_final"]
    assert metric["context_ready_wait"] is not None
    # Selected frames were in before the cutoff; nothing waited for them, so no wait is shown.
    assert metric["last_selected_frame_to_cutoff"] > 0
    for name in ("vision_wait", "first_visual_output_frame"):
        assert (metric[name], metrics[name]["samples"]) == (None, 0)
    # The speech synthesis stages come from its own log lines: these guard their wording.
    assert None not in (
        metric["tts_text_ready_to_request"],
        metric["tts_request_to_first_audio_frame"],
    )
    assert metric["output_events_dropped"] == 0

    # Each external service: configured, authorized, reached and passed, or why not known.
    services = {s["name"]: s for s in checks["services.external"]["services"]}
    assert services["speech recognition (openai_segment)"]["passed"] is True
    assert services["speech synthesis (openai)"]["passed"] is True
    assert services["model providers (scripted)"]["passed"] is True
    custom = services["custom memory 'doctor'"]
    assert (custom["reached"], custom["note"]) == (None, "external access unknown")
    assert checks["services.external"]["status"] == "PASS"

    # The text shows each scenario; nothing was written outside the temporary workspace.
    chain.spec["stt"] = [CARD]
    # 1: the stand-in backend is no installed provider package, as packages.capabilities says.
    assert doctor(capsys, chain, str(path), json_output=False)[0] == 1
    shown = capsys.readouterr().out
    assert "passed       voice_vision" in shown and "no coverage  image_input" in shown
    # The figures table: a column per measured scenario, a dash where none was observed.
    rows = {line.split()[0]: line.split()[1:] for line in shown.splitlines() if line.strip()}
    assert rows["FIGURE"] == ["(ms)", "voice_vision", "text"]
    assert all(value.isdigit() for value in rows["first_text"])  # Observed in both turns.
    assert rows["vad_close"][1] == "-"
    assert not (tmp_path / "home" / "avatars").exists()
    assert list(chain.root.iterdir()) == []

    # What was checked and authorized is what starts: the file changing in between does not
    # reach the diagnostic process, which runs the snapshot loaded first.
    diagnosis = prepare(str(path))
    path.write_text(json.dumps(json.loads(path.read_text()) | {"vision": {"enabled": False}}))
    environ = dict(os.environ) | {doubles.SPEC: json.dumps(chain.spec | {"stt": [CARD]})}
    with mock.patch.dict(os.environ, environ, clear=True):
        report = asyncio.run(diagnosis.run()).to_dict()
    ran = {s["name"]: s["outcome"] for c in report["checks"] for s in c["scenarios"]}
    assert (ran["voice_vision"], "voice" in ran) == ("passed", False)


def test_degradations_follow_the_original_cause_and_both_configurations_are_reported(
    tmp_path: Path,
    chain: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    path = configuration(tmp_path)
    # Turns end on their own outputs here, well inside this; ending by timeout would be a stall.
    monkeypatch.setattr(doctor_session, "TURN_SECONDS", 10.0)

    # A model without image input: the original stops at the model, audio alone answers.
    chain.spec |= {"llm": {"images": False}, "stt": [CARD, SUM]}
    code, checks = doctor(capsys, chain, str(path))
    found = scenarios(checks)
    original = found["voice_vision", "original"]
    assert (original["outcome"], original["blocked_stage"], original["cause"]) == (
        "failed",
        "model.first_event",
        "ModelCapabilityError: image_input",
    )
    # Context selected the frames and the request carried them: the model refused them.
    assert original["request"]["sample_frames"] > 0
    degraded = found["voice", "degraded: vision off"]
    assert (degraded["outcome"], degraded["transcript"], degraded["answer"]) == (
        "passed",
        SUM,
        "5.",
    )
    assert not degraded["frames"] and not requests(chain)[-1]["images"]
    model = next(
        s for s in checks["services.external"]["services"] if s["name"].startswith("model")
    )
    # It answered the audio-only turn, and refused the original's: reached, not passed.
    assert (model["reached"], model["passed"], model["note"]) == (
        True,
        False,
        "ModelCapabilityError: image_input",
    )
    assert code == 1 and checks["session.scenarios"]["status"] == "FAIL"

    # Only vision's runner cannot start: the original is blocked there, and the plan without
    # vision has no such runner, so audio and text are verified on their own.
    chain.spec |= {"llm": {}, "stt": [SUM], "vision_runners": ["MissingModelRunner"]}
    _, checks = doctor(capsys, chain, str(path))
    found = scenarios(checks)
    runners = {
        (r["method"], r["configuration"]): r["status"] for r in checks["models.runners"]["runners"]
    }
    assert runners[doubles.MissingModelRunner.INFERENCE_METHOD, "original"] == "FAIL"
    assert ("test.doctor.face", "degraded: vision off") not in runners
    assert runners[doubles.SpeechRunner.INFERENCE_METHOD, "degraded: vision off"] == "PASS"
    assert (checks["models.runners"]["status"], checks["session.start"]["status"]) == ("FAIL",) * 2
    assert found["voice_vision", "original"]["blocked_stage"] == "runners"
    assert found["voice", "degraded: vision off"]["outcome"] == "passed"
    assert found["text", "degraded: vision off"]["outcome"] == "passed"

    # Two outputs; the second's speech fails after its first frame. Each output is judged:
    # one completed, one failed, so nothing records a completion and audio is degraded to text.
    del chain.spec["vision_runners"]
    chain.spec |= {"llm": {"messages": 2}, "stt": [CARD], "tts": {"fail_after": {"2": 1}}}
    _, checks = doctor(capsys, chain, str(path))
    found = scenarios(checks)
    original = found["voice_vision", "original"]
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
    assert ("voice", "degraded: vision off") not in found  # Vision was not what failed.
    degraded = found["text", "degraded: text output"]
    assert degraded["outcome"] == "passed" and degraded["outputs"][0]["modalities"] == "text"
    assert {m["name"]: m["value"] for m in degraded["metrics"]}["first_audio_frame"] is None
    tts = next(
        s for s in checks["services.external"]["services"] if s["name"].startswith("speech s")
    )
    assert (tts["reached"], tts["passed"]) == (True, False)

    # The request keeps the Turn's input and the frames but not its speech: not one turn.
    chain.spec |= {"drop_speech": True, "llm": {}, "tts": {}, "stt": [CARD]}
    _, checks = doctor(capsys, chain, str(path))
    original = scenarios(checks)["voice_vision", "original"]
    assert (original["outcome"], original["blocked_stage"]) == ("failed", "request.content")
    request = original["request"]
    assert request["carries_turn_input"] and request["sample_frames"] > 0
    assert not request["carries_turn_content"]
    assert "The model request does not carry this Turn's transcript" in original["details"]
    assert {configuration for _, configuration in scenarios(checks)} == {"original"}
    del chain.spec["drop_speech"]

    # Rejected credentials are the model's failure, named as such: no degradation is tried.
    chain.spec |= {"llm": {"error": "invalid_api_key"}, "tts": {}, "stt": [CARD]}
    _, checks = doctor(capsys, chain, str(path))
    found = scenarios(checks)
    assert found["voice_vision", "original"]["cause"] == "ModelRequestError: invalid_api_key"
    assert {configuration for _, configuration in found} == {"original"}
    # A capability the backend lacks that is not about pictures: no vision fallback either.
    chain.spec |= {"llm": {"error": "capability"}, "stt": [CARD]}
    _, checks = doctor(capsys, chain, str(path))
    found = scenarios(checks)
    assert found["voice_vision", "original"]["cause"] == "ModelCapabilityError"
    assert {configuration for _, configuration in found} == {"original"}
    assert checks["session.cleanup"]["status"] == "PASS"


def test_an_answer_passes_only_when_it_is_exactly_the_expected_one(
    tmp_path: Path, chain: SimpleNamespace, capsys: pytest.CaptureFixture
) -> None:
    card, total = samples.VOICE_VISION, samples.TEXT
    for answer in ("Green.", "green", '"Green"', "绿色。"):
        assert card.answered(answer), answer
    # Wrong, negated, hedged or questioning; a longer sentence is not a one-word answer.
    for answer in ("Red.", "Not green.", "The card is not green. It is red.", "Maybe green."):
        assert not card.answered(answer), answer
    for answer in ("Green?", "The card is green.", "I cannot tell."):
        assert not card.answered(answer), answer
    for answer in ("5", "5.", "Five!", "五"):
        assert total.answered(answer), answer
    # Another number that merely contains the digit is a wrong number.
    for answer in ("15", "25.", "5.5", "-5", "It is 5.", "five or six"):
        assert not total.answered(answer), answer
    assert samples.VOICE.heard(SUM) and not samples.VOICE.heard("What is 12 plus 13?")

    # The session judges with the same rule: a typed turn answered with the wrong number.
    text_only = {
        "voice": {"vad": {"plugin": None}, "stt": {"plugin": None}, "tts": {"plugin": None}},
        "router": {"init_config": {"turn_taking": {"enabled": False}}},
    }
    chain.spec |= {"runners": {}, "llm": {"answers": {"sum": "15."}}}
    _, checks = doctor(capsys, chain, str(configuration(tmp_path, **text_only)))
    text = scenarios(checks)["text", "original"]
    assert (text["outcome"], text["blocked_stage"], text["answer"]) == ("failed", "answer", "15.")
    assert checks["session.scenarios"]["status"] == "FAIL"
    # No runner is a valid plan: nothing to start there, and the session itself started.
    assert checks["models.runners"]["summary"] == "Not started: no runner selected"
    assert (checks["models.runners"]["status"], checks["session.start"]["status"]) == (
        "SKIP",
        "PASS",
    )


def wait_for(path: Path, seconds: float = 30.0) -> None:
    deadline = time.monotonic() + seconds
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.002)
    assert path.exists(), f"{path.name} never appeared"


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
    assert scenarios(checks)["voice_vision", "original"]["outcome"] == "conditions_unmet"
    assert (code, checks["session.cleanup"]["status"]) == (1, "PASS")
    assert "private" not in json.dumps(checks)

    # A start that outlives its deadline is ended there, and its process reclaimed.
    voice["voice"] = ["StuckRunner", "SpeechRunner"]
    monkeypatch.setattr(doctor_session, "SESSION_SECONDS", 1.0)
    _, checks = doctor(capsys, chain, str(path))
    assert checks["models.runners"]["details"] == ["the runners did not start within 1 s"]
    assert (checks["session.start"]["status"], checks["session.cleanup"]["status"]) == (
        "FAIL",
        "PASS",
    )
    monkeypatch.setattr(doctor_session, "SESSION_SECONDS", 180.0)

    # A turn still speaking at its deadline: its outputs timed out, its playback and outputs
    # end with it, and the next turn gets a session of its own.
    voice["voice"] = ["SpeechRunner"]
    chain.spec["tts"] = {"frames": 200}  # Four seconds of speech per answer.
    monkeypatch.setattr(doctor_session, "TURN_SECONDS", 3.0)
    _, checks = doctor(capsys, chain, str(path))
    found = scenarios(checks)
    timed_out, text = found["voice_vision", "original"], found["text", "original"]
    assert timed_out["outcome"] == "failed" and "Ended by timeout" in timed_out["details"]
    assert [item["terminal"] for item in timed_out["outputs"]] == ["timed_out"]
    assert timed_out["blocked_stage"] == "outputs.complete"
    assert {m["name"]: m["value"] for m in timed_out["metrics"]}["response_final"] is None
    assert text["evidence"] and text["request"]["turn"] != timed_out["request"]["turn"]
    assert checks["session.cleanup"]["status"] == "PASS"
    assert checks["session.cleanup"]["summary"].startswith("3 owned parts closed")

    # A spent budget starts nothing more, and says so rather than failing a runner.
    monkeypatch.setattr(doctor_session, "TOTAL_SECONDS", 0.0)
    _, checks = doctor(capsys, chain, str(path))
    assert checks["models.runners"]["summary"] == (
        "Not started: the diagnosis budget was spent before the runners started"
    )
    assert checks["session.start"]["status"] == "SKIP"
    assert {s["blocked_stage"] for s in checks["session.scenarios"]["scenarios"][:2]} == {
        "not run: budget exhausted"
    }


async def test_a_step_keeps_the_state_its_wait_ended_in(tmp_path: Path) -> None:
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
    assert found["voice_vision", "original"]["outcome"] == "interrupted"
    assert found["text", "original"]["outcome"] == "interrupted"
    assert checks["session.cleanup"]["status"] == "PASS"
    assert gone(int((chain.files / "pid").read_text()))

    # Cancelling the diagnosis itself: the process and its runners go before it returns.
    async def cancelled() -> None:
        diagnosis = prepare(str(path))
        task = asyncio.create_task(diagnosis.run())
        await asyncio.to_thread(wait_for, chain.files / "committed")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    (chain.files / "committed").unlink()
    environ = dict(os.environ) | {doubles.SPEC: json.dumps(chain.spec | {"stt": [CARD]})}
    with mock.patch.dict(os.environ, environ, clear=True):
        asyncio.run(cancelled())
        assert dict(os.environ) == environ
    assert gone(int((chain.files / "pid").read_text()))
    assert list(chain.root.iterdir()) == []


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
    monkeypatch.setattr(doctor_session, "TOTAL_SECONDS", 2.0)
    monkeypatch.setattr(doctor_process, "CLOSE_SECONDS", 1.0)
    began = time.monotonic()
    code, checks = doctor(capsys, chain, str(path))
    assert time.monotonic() - began < 15
    assert code == 1
    cleanup = checks["session.cleanup"]
    assert cleanup["status"] == "FAIL"
    assert "the diagnostic process did not exit within 1 s: killed" in cleanup["details"]
    assert checks["session.start"]["details"] == ["the diagnostic process exited with code -9"]
    assert gone(int((chain.files / "pid").read_text()))
    with pytest.raises(ProcessLookupError):  # Its runner went with its group.
        os.kill(int((chain.files / "stuck").read_text()), 0)
    # Its runtime's socket was under Doctor's directory, removed with it, not left in /tmp.
    assert list(chain.root.iterdir()) == []
    assert {*Path("/tmp").glob("alphaavatar-inference-*")} <= sockets


@pytest.fixture
def provider(socket_root: Path):
    """An HTTP stand-in for the OpenAI API on loopback: it refuses every request."""
    refusal = {"status": 401}

    class Refuse(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.dumps({"error": {"message": "refused", "type": "invalid_request_error"}})
            self.send_response(refusal["status"])
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
        yield SimpleNamespace(port=server.server_address[1], refusal=refusal)
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
    chain.spec |= {"loopback": provider.port, "stt": [CARD, SUM]}

    # The real Responses adapter cannot inline frames this large: it refuses the pictures
    # itself, before any call. Doctor then tries the audio session, whose request goes out
    # and is refused by the service, with that classification.
    small = model | {"input_options": {"max_inline_bytes": 1024}}
    loop = {"plugin": "realtime", "init_config": {"model": small}}
    _, checks = doctor(capsys, chain, str(configuration(tmp_path, loop=loop)))
    found = scenarios(checks)
    assert found["voice_vision", "original"]["cause"] == "ModelCapabilityError: image_input"
    degraded = found["voice", "degraded: vision off"]
    assert (degraded["blocked_stage"], degraded["cause"]) == (
        "model.first_event",
        "ModelRequestError: http_401",
    )

    # A generic HTTP 400 for the request with pictures is the service's, as classified:
    # nothing shows it is about vision, so no fallback runs.
    provider.refusal["status"] = 400
    chain.spec["stt"] = [CARD]
    loop = {"plugin": "realtime", "init_config": {"model": model}}
    _, checks = doctor(capsys, chain, str(configuration(tmp_path, loop=loop)))
    found = scenarios(checks)
    assert found["voice_vision", "original"]["cause"] == "ModelRequestError: http_400"
    assert {configuration for _, configuration in found} == {"original"}
    assert checks["session.cleanup"]["status"] == "PASS"


def test_the_diagnostic_process_leaves_a_calling_host_and_its_report_stdout_alone(
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
            main(["doctor", str(configuration(tmp_path)), "--json"])
            assert dict(os.environ) == environ
        out, err = capfd.readouterr()
        checks = {check["id"]: check for check in json.loads(out)["checks"]}  # Only the report.
        assert "stand-in STT committed" in err and "stand-in VAD runner started" in err
        assert [checks[c]["status"] for c in ("session.start", "models.runners")] == ["PASS"] * 2
        assert scenarios(checks)["voice_vision", "original"]["outcome"] == "passed"
        with pytest.raises(BlockingIOError):  # Nothing of it reached the Host's receiver.
            receiver.recv(65536)
    finally:
        receiver.close()
        (chain.root / "host-log.sock").unlink()
