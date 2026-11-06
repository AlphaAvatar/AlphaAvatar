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
        "stt": [CARD, SUM],  # The card question, then the two-sentence one
        "runners": {"voice": ["SpeechRunner"], "router": ["EndpointRunner"]},
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
        doubles.EndpointRunner.INFERENCE_METHOD,
    }
    found = scenarios(checks)
    vision, text = found["voice_vision", "original"], found["text", "original"]
    voice = found["voice", "original"]
    assert (vision["outcome"], voice["outcome"], text["outcome"]) == ("passed",) * 3
    assert (vision["transcript"], vision["answer"], text["answer"]) == (CARD, "Green.", "5.")
    # The two-sentence question as its own scenario: both sentences heard, in one segment.
    assert (voice["transcript"], voice["answer"]) == (SUM, "5.")
    assert [(x["index"], x["heard"], x["lost"]) for x in voice["sentences"]] == [
        (1, True, None),
        (2, True, None),
    ]
    # Each scenario in a session of its own, each a first round.
    assert {vision["round"], voice["round"], text["round"]} == {1}
    assert checks["session.start"]["metrics"][0]["samples"] == 3
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
        "runtime_start",
        "queue_wait_max",
        "execution_max",
    }
    # One runtime start, one sample: nothing fetched, every model file from the cache.
    start = checks["models.runners"]["metrics"][0]
    assert (start["name"], start["note"]) == ("runtime_start", "every model file from the cache")

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
    # The stand-in model's provider logs no request it sends: each of those figures says so.
    for name in ("model_request_encode", "model_request_frames", "model_request_bytes"):
        assert (metric[name], metrics[name]["note"]) == (
            None,
            "no record of it sent: none went out, or its provider logs none",
        )

    # Each external service: configured, authorized, reached and passed, or why not known.
    services = {s["name"]: s for s in checks["services.external"]["services"]}
    assert services["speech recognition (openai_segment)"]["passed"] is True
    assert services["speech synthesis (openai)"]["passed"] is True
    assert services["model providers (scripted)"]["passed"] is True
    custom = services["custom memory 'doctor'"]
    assert (custom["reached"], custom["note"]) == (None, "external access unknown")
    assert checks["services.external"]["status"] == "PASS"

    # The text shows each scenario; nothing was written outside the temporary workspace.
    # The stand-ins resolve here as installed plugins would: every check passes.
    assert doctor(capsys, chain, str(path), json_output=False)[0] == 0
    shown = capsys.readouterr().out
    rows = {tuple(line.split()[:2]): line.split()[2:] for line in shown.splitlines()}
    covers = samples.VOICE_VISION.covers.split()
    assert rows["PASS", "voice_vision"] == ["1/1", "passed", "·", *covers]
    assert rows["SKIP", "image_input"] == found["image_input", "original"]["summary"].split()
    # Each scenario's figures, grouped as a turn passes them: speech ones only where speech
    # went in; one round, so only its own column holds a value.
    tables = {
        block.split(" · ")[0]: block.split("\n\n")[0] for block in shown.split("\nLatency · ")[1:]
    }
    assert "Speech end → VAD close" in tables["voice_vision"]
    assert "Model request → First text delta" in tables["text"]
    assert "Speech end → VAD close" not in tables["text"]
    host = next(line for line in tables["text"].splitlines() if "Host first text" in line)
    assert re.fullmatch(r"\s+Host first text\s+[\d,.]+ ms\s+0\s+—\s+—", host)
    assert not (tmp_path / "home" / "avatars").exists()
    assert list(chain.root.iterdir()) == []

    # What was checked and authorized is what starts: the file changing in between does not
    # reach the diagnostic process, which runs the snapshot loaded first.
    diagnosis = prepare(str(path), rounds=1)
    path.write_text(json.dumps(json.loads(path.read_text()) | {"vision": {"enabled": False}}))
    environ = dict(os.environ) | {doubles.SPEC: json.dumps(chain.spec | {"stt": [CARD, SUM]})}
    with mock.patch.dict(os.environ, environ, clear=True):
        report = asyncio.run(diagnosis.run()).to_dict()
    ran = {s["name"]: s["outcome"] for c in report["checks"] for s in c["scenarios"]}
    assert ran["voice_vision"] == "passed"  # Vision on, as loaded and checked


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
    # The spoken turn without a picture, in a session of its own, answered: the camera-less
    # fallback would show nothing more, so it is not run.
    voice = found["voice", "original"]
    assert (voice["outcome"], voice["transcript"], voice["answer"]) == ("passed", SUM, "5.")
    assert not voice["frames"] and not requests(chain)[1]["images"]
    assert {configuration for _, configuration in found} == {"original"}
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
    chain.spec |= {"llm": {"messages": 2}, "stt": [CARD, SUM], "tts": {"fail_after": {"2": 1}}}
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
    chain.spec |= {"drop_speech": True, "llm": {}, "tts": {}, "stt": [CARD, SUM]}
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
    chain.spec |= {"llm": {"error": "invalid_api_key"}, "tts": {}, "stt": [CARD, SUM]}
    _, checks = doctor(capsys, chain, str(path))
    found = scenarios(checks)
    assert found["voice_vision", "original"]["cause"] == "ModelRequestError: invalid_api_key"
    assert {configuration for _, configuration in found} == {"original"}
    # A capability the backend lacks that is not about pictures: no vision fallback either.
    chain.spec |= {"llm": {"error": "capability"}, "stt": [CARD, SUM]}
    _, checks = doctor(capsys, chain, str(path))
    found = scenarios(checks)
    assert found["voice_vision", "original"]["cause"] == "ModelCapabilityError"
    assert {configuration for _, configuration in found} == {"original"}
    assert checks["session.cleanup"]["status"] == "PASS"


def test_an_answer_passes_only_when_it_clearly_is_the_expected_one(
    tmp_path: Path, chain: SimpleNamespace, capsys: pytest.CaptureFixture
) -> None:
    card, total = samples.VOICE_VISION, samples.TEXT
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
    # end with it; each scenario has a session of its own anyway.
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
    # The runtime and each scenario's session: closed, each.
    assert checks["session.cleanup"]["summary"].startswith("4 owned parts closed")

    # A spent budget starts nothing more, and says so rather than failing a runner.
    spent = doctor_session.Budget(180.0, 60.0, 0.0)
    monkeypatch.setattr(doctor_session, "budget", lambda *args: spent)
    _, checks = doctor(capsys, chain, str(path))
    assert checks["models.runners"]["summary"] == (
        "Not started: the diagnosis budget was spent before the runners started"
    )
    assert checks["session.start"]["status"] == "SKIP"
    assert {s["blocked_stage"] for s in checks["session.scenarios"]["scenarios"][:2]} == {
        "not run: budget exhausted"
    }


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
    assert found["voice_vision", "original"]["outcome"] == "interrupted"
    assert found["text", "original"]["outcome"] == "interrupted"
    assert checks["session.cleanup"]["status"] == "PASS"
    assert gone(int((chain.files / "pid").read_text()))

    # Cancelling the diagnosis itself: the process and its runners go before it returns.
    async def cancelled() -> None:
        diagnosis = prepare(str(path), rounds=1)
        task = asyncio.create_task(diagnosis.run())
        await asyncio.to_thread(wait_for, chain.files / "committed")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    (chain.files / "committed").unlink()
    environ = dict(os.environ) | {doubles.SPEC: json.dumps(chain.spec | {"stt": [CARD, SUM]})}
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
    refusal = {"status": 401}
    sizes: list[int] = []

    class Refuse(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            sizes.append(len(self.rfile.read(length)))
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
    chain.spec |= {"loopback": provider.port, "stt": [CARD, SUM, SUM]}

    # The real Responses adapter cannot inline frames this large: it refuses the pictures
    # itself, before any call. The spoken turn without them goes out and is refused by the
    # service, with that classification; so is the camera-less fallback's.
    small = model | {"input_options": {"max_inline_bytes": 1024}}
    loop = {"plugin": "realtime", "init_config": {"model": small}}
    _, checks = doctor(capsys, chain, str(configuration(tmp_path, loop=loop)))
    found = scenarios(checks)
    vision = found["voice_vision", "original"]
    assert vision["cause"] == "ModelCapabilityError: image_input"
    # Refused before a call: no request went out, and the figures say no more than that.
    sent = {m["name"]: m for m in vision["segments"]}
    assert sent["model_request_bytes"]["value"] is None
    # The spoken turn's request did go out: its provider recorded it in numbers alone, the
    # body as the transport sent it, no picture in it, encoded here once.
    voice = found["voice", "original"]
    assert voice["cause"] == "ModelRequestError: http_401"
    sent = {m["name"]: m["value"] for m in voice["segments"]}
    assert sent["model_request_frames"] == 0 and sent["model_request_encode"] >= 0
    assert sent["model_request_bytes"] == provider.sizes[0] > 0
    degraded = found["voice", "degraded: vision off"]
    assert (degraded["blocked_stage"], degraded["cause"]) == (
        "model.first_event",
        "ModelRequestError: http_401",
    )

    # A generic HTTP 400 for the request with pictures is the service's, as classified:
    # nothing shows it is about vision, so no fallback runs.
    provider.refusal["status"] = 400
    chain.spec["stt"] = [CARD, SUM]
    loop = {"plugin": "realtime", "init_config": {"model": model}}
    _, checks = doctor(capsys, chain, str(configuration(tmp_path, loop=loop)))
    found = scenarios(checks)
    assert found["voice_vision", "original"]["cause"] == "ModelRequestError: http_400"
    assert {configuration for _, configuration in found} == {"original"}
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
        assert scenarios(checks)["voice_vision", "original"]["outcome"] == "passed"
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
    assert "then runs each scenario once, each time in a session of its own:" in output.err
    for name in ("voice_vision", "voice", "text"):
        assert f"\n    {name} " in output.err
    assert "Model files the cache lacks are downloaded first, as start would." in output.err
    for name in ("model providers (scripted)", "speech recognition (openai_segment)"):
        assert f"    {name}\n" in output.err
    assert "Calls to these services may be billed." in output.err
    found = scenarios(checks)
    if agreed:
        assert code == 0 and found["voice_vision", "original"]["outcome"] == "passed"
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
    run.runners["original"] = [
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
    run.runner_error["original"] = error
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
    assert runs == [{"rounds": 1, "runners": 2 * 300.0 + 30.0}]
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


def test_each_scenario_runs_in_rounds_each_in_a_session_and_the_rounds_are_summarized(
    tmp_path: Path, chain: SimpleNamespace, capsys: pytest.CaptureFixture
) -> None:
    import statistics

    # Round 2 of the two-sentence question loses its second sentence in STT; the rest pass.
    chain.spec["stt"] = [CARD, SUM, CARD, "What is two plus three?", CARD, SUM]
    code, checks = doctor(capsys, chain, str(configuration(tmp_path)), rounds=3)
    assert code == 1 and checks["session.scenarios"]["status"] == "FAIL"
    summaries = {
        (x["name"], x["configuration"]): x for x in checks["session.scenarios"]["summaries"]
    }
    assert set(summaries) == {
        ("voice_vision", "original"),
        ("voice", "original"),
        ("text", "original"),
    }
    voice = summaries["voice", "original"]
    assert (voice["rounds"], voice["passed"], voice["stopped_at"]) == (3, 2, {"stt.final": 1})
    assert summaries["voice_vision", "original"]["passed"] == 3
    assert summaries["text", "original"]["passed"] == 3
    # The failed round: the sentence it lost, and the layer that lost it.
    rounds = checks["session.scenarios"]["scenarios"]
    failed = [r for r in rounds if r["outcome"] == "failed"]
    assert [(r["name"], r["round"]) for r in failed] == [("voice", 2)]
    lost = [(s["index"], s["lost"]) for s in failed[0]["sentences"] if not s["heard"]]
    assert lost == [(2, "stt")]
    assert any(
        line.startswith("Sentence 2: its segment's STT final") for line in failed[0]["details"]
    )
    # Each figure over the passed rounds: the first round apart, then the later ones.
    cards = [r for r in rounds if r["name"] == "voice_vision"]
    values = {
        r["round"]: {m["name"]: m["value"] for m in r["metrics"]}["first_text"] for r in cards
    }
    figure = {f["name"]: f for f in summaries["voice_vision", "original"]["figures"]}["first_text"]
    later = sorted((values[2], values[3]))
    assert (figure["first"], figure["samples"]) == (values[1], 2)
    assert (figure["median"], figure["low"], figure["high"]) == (
        round(statistics.median(later), 3),
        later[0],
        later[-1],
    )
    assert figure["p95"] is None  # Two samples: the range says it all.
    # The failed round is no sample: of the voice question's later rounds, round 3 alone.
    figure = {f["name"]: f for f in voice["figures"]}["first_text"]
    assert figure["samples"] == 1
    # One runtime start for every round; a session for each of the nine turns.
    starts = [m for m in checks["models.runners"]["metrics"] if m["name"] == "runtime_start"]
    assert len(starts) == 1 and checks["session.start"]["metrics"][0]["samples"] == 9
    assert checks["session.cleanup"]["status"] == "PASS"
    assert list(chain.root.iterdir()) == []


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
    assert start(checks)["note"] == "64.0 KB of model files downloaded first"
    assert (chain.files / "model.log").read_text().splitlines() == ["download"]
    # The next start loads them: a cached start, a sample of its own kind.
    _, checks = doctor(capsys, chain, str(path), online=True)
    assert start(checks)["note"] == "every model file from the cache"
    assert (chain.files / "model.log").read_text().splitlines() == ["download", "cache"]
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
    chain.spec["stt"] = [CARD, SUM, CARD, SUM]

    def interrupt() -> None:
        # The first round's two spoken segments, then the second round's first one.
        wait_lines(chain.files / "committed", 3)
        os.kill(os.getpid(), signal.SIGINT)

    thread = threading.Thread(target=interrupt)
    thread.start()
    try:
        code, checks = doctor(capsys, chain, str(configuration(tmp_path)), rounds=2)
    finally:
        thread.join()
    assert code == 130
    rounds = {
        (r["name"], r["round"]): r["outcome"]
        for r in checks["session.scenarios"]["scenarios"]
        if r["round"]
    }
    # Round 1 ran whole; round 2 stopped in its first turn, and the rest of it did not run.
    assert [rounds[name, 1] for name in ("voice_vision", "voice", "text")] == ["passed"] * 3
    assert [rounds[name, 2] for name in ("voice_vision", "voice", "text")] == ["interrupted"] * 3
    summaries = {x["name"]: x for x in checks["session.scenarios"]["summaries"]}
    assert (summaries["voice_vision"]["passed"], summaries["voice_vision"]["rounds"]) == (1, 2)
    assert checks["session.cleanup"]["status"] == "PASS"
    assert gone(int((chain.files / "pid").read_text()))
    assert list(chain.root.iterdir()) == []
