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

Only the external services and the model files are replaced (``doctor_doubles``): the
Router, Context, Loop, Engine, output runtime and shared inference are production code.
These tests check correlation, timing definitions, degradation and reclamation; what a
real model, STT or TTS measures is recorded separately, in the T-10C log.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import doctor_doubles as doubles
import numpy as np
import pytest
from inference_runner_samples import FailingInitRunner

# Imported at collection: configuration plugins adjust process variables while importing (O-2).
import alphaavatar.agents.configs  # noqa: F401
from alphaavatar.agents.avatar.provider import factory
from alphaavatar.agents.runtime.inference import InferenceExecutor, bootstrap as inference_bootstrap
from alphaavatar.agents.runtime.plugin import AvatarModule, AvatarModulePlugin
from alphaavatar.host.cli.app import main
from alphaavatar.host.doctor import samples, session as doctor_session

CARD = "What color is the card on my screen?"
SUM = "What is two plus three?"


class _Factory(AvatarModulePlugin):
    def __init__(self, create) -> None:
        super().__init__("doctor doubles", "0", "tests")
        self.create = create

    def get_plugin(self, *args: object, **kwargs: object) -> object:
        return self.create()


@pytest.fixture
def chain(monkeypatch: pytest.MonkeyPatch, owned_endpoints: set[object], socket_root: Path):
    """The stand-ins, plugged in where the configuration names its plugins and runners."""
    found = SimpleNamespace(
        llm=doubles.ScriptedLLM(), stt=doubles.ScriptedSTT([CARD]), tts=doubles.ScriptedTTS()
    )
    registry = AvatarModulePlugin._registry
    for module, name, create in (
        (AvatarModule.PROVIDER_LLM, "scripted", lambda: found.llm),
        (AvatarModule.VOICE_STT, "openai_segment", lambda: found.stt),
        (AvatarModule.VOICE_TTS, "openai", lambda: found.tts),
        (AvatarModule.MEMORY, "doctor", doubles.NullMemory),
        (AvatarModule.PERSONA, "doctor", doubles.NullPersona),
    ):
        monkeypatch.setitem(registry, module, dict(registry.get(module, {})))
        registry[module][name] = _Factory(create)
    load = factory._load_backend
    monkeypatch.setattr(factory, "_load_backend", lambda name: name == "scripted" or load(name))
    bootstraps = inference_bootstrap._runner_bootstraps
    found.runners = {"voice": (doubles.SpeechRunner,), "router": (doubles.EndpointRunner,)}
    for name in found.runners:
        plan = lambda config, name=name: found.runners[name]  # noqa: E731
        monkeypatch.setitem(bootstraps, f"alphaavatar.plugins.{name}", plan)
    # A second of loud noise is speech to the stand-in VAD; silence follows, as from a mic.
    noise = np.random.default_rng(7).standard_normal(samples.SAMPLE_RATE) * 6000
    voiced = noise.astype("<i2").tobytes()
    monkeypatch.setattr(samples, "speech", lambda name: samples.Speech(name, voiced, 1.0))
    # The session's runtime endpoint is the test's own, so its executors may reach it.
    connect = InferenceExecutor.__init__

    def owned(executor: InferenceExecutor, endpoint: str, *args: object, **kwargs: object):
        owned_endpoints.add(endpoint)
        connect(executor, endpoint, *args, **kwargs)

    monkeypatch.setattr(InferenceExecutor, "__init__", owned)
    found.root = socket_root
    return found


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


def doctor(capsys: pytest.CaptureFixture, *argv: str) -> tuple[int, dict[str, dict]]:
    code = main(["doctor", *argv, "--json"])
    report = json.loads(capsys.readouterr().out)
    assert code in (130, 1 if report["status"] == "FAIL" else 0)
    return code, {check["id"]: check for check in report["checks"]}


def scenarios(checks: dict[str, dict]) -> dict[tuple[str, str], dict]:
    return {(s["name"], s["configuration"]): s for s in checks["session.scenarios"]["scenarios"]}


def test_the_configured_chain_runs_fixed_samples_and_its_evidence_joins_by_identity(
    tmp_path: Path, chain: SimpleNamespace, capsys: pytest.CaptureFixture
) -> None:
    path = configuration(tmp_path)
    level = logging.getLogger("alphaavatar").level
    # Downloads allowed here: the session switches them off for itself and its runners only.
    online = {name: value for name, value in os.environ.items() if "OFFLINE" not in name}
    with mock.patch.dict(os.environ, online, clear=True):
        _, checks = doctor(capsys, str(path))
        assert {"ALPHAAVATAR_MODEL_OFFLINE", "HF_HUB_OFFLINE"}.isdisjoint(os.environ)
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
    assert (vision["transcript"], vision["answer"]) == (CARD, "The card is green.")
    assert found["image_input", "original"]["outcome"] == "no_coverage"
    assert found["visual_output", "original"]["outcome"] == "not_enabled"

    # The spoken question and the selected frames went into one model request.
    request = chain.llm.requests[0]
    parts = doubles.ScriptedLLM.parts(request)
    images = [part for part in parts if type(part).__name__ == "ModelImagePart"]
    assert any(CARD in getattr(part, "text", "") for part in parts) and images
    assert len(images) == len(vision["frames"]) and all(f["matched"] for f in vision["frames"])

    # Evidence follows the chain, joined through the trace's own identities.
    order = [item["stage"] for item in vision["evidence"]]
    chain_order = [
        "input.voiced_end",
        "perception.speech_closed",
        "stt.terminal",
        "turn.committed",
        "context.frame_selected",
        "model.started",
        "output.text_chunk",
        "output.audio_frame",
    ]
    assert [stage for stage in order if stage in chain_order][:1] == ["input.voiced_end"]
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
    assert {first[stage]["turn"] for stage in chain_order[4:]} == {turn}
    assert {m["name"] for m in checks["models.runners"]["metrics"]} == {
        "queue_wait_max",
        "execution_max",
    }

    # One clock: the segments add up to the end-to-end figure they divide.
    metric = {m["name"]: m["value"] for m in vision["metrics"] + vision["segments"]}
    parts_sum = (
        metric["turn_cutoff"] + metric["cutoff_to_model_request"] + metric["model_first_text"]
    )
    assert parts_sum == pytest.approx(metric["first_text"], abs=0.01)
    assert metric["vad_close"] <= metric["stt_final"] <= metric["turn_cutoff"]
    assert metric["first_text"] <= metric["text_complete"] <= metric["response_final"]
    assert metric["first_audio_frame"] <= metric["audio_last_frame"] <= metric["response_final"]
    assert metric["first_visual_output_frame"] is None
    assert metric["vision_wait"] == 0  # Frames are taken up to the cutoff, never waited for.
    # The speech synthesis stages come from its own log lines: these guard their wording.
    assert None not in (
        metric["tts_text_ready_to_request"],
        metric["tts_request_to_first_audio_frame"],
    )
    assert metric["output_events_dropped"] == 0

    # The text shows each scenario; nothing was written outside the temporary workspace.
    chain.stt.transcripts[:] = [CARD]
    assert main(["doctor", str(path)]) in (0, 1)
    shown = capsys.readouterr().out
    assert "passed       voice_vision" in shown and "no coverage  image_input" in shown
    assert not (tmp_path / "home" / "avatars").exists()
    assert list(chain.root.iterdir()) == []


def test_unavailable_vision_or_speech_runs_the_existing_fallback_and_both_are_reported(
    tmp_path: Path,
    chain: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    path = configuration(tmp_path)
    # Turns end on their own outputs here, well inside this; ending by timeout would be a stall.
    monkeypatch.setattr(doctor_session, "TURN_SECONDS", 10.0)
    # A model without image input: the original stops at the model, audio alone answers.
    chain.llm.images = False
    chain.stt.transcripts[:] = [CARD, SUM]
    code, checks = doctor(capsys, str(path))
    found = scenarios(checks)
    original = found["voice_vision", "original"]
    assert (original["outcome"], original["blocked_stage"]) == ("failed", "model.first_event")
    degraded = found["voice", "degraded: vision off"]
    assert (degraded["outcome"], degraded["transcript"]) == ("passed", SUM)
    assert not degraded["frames"] and "five" in degraded["answer"]
    assert code == 1 and checks["session.scenarios"]["status"] == "FAIL"

    # Speech output unavailable: the original stops before audio, text alone answers.
    chain.llm.images, chain.tts.fail = True, True
    chain.stt.transcripts[:] = [CARD]
    _, checks = doctor(capsys, str(path))
    found = scenarios(checks)
    assert found["voice_vision", "original"]["blocked_stage"] == "audio.first"
    assert not any(result["details"] for result in found.values())  # None ended by timeout.
    assert ("voice", "degraded: vision off") not in found  # Vision was not what failed.
    degraded = found["text", "degraded: text output"]
    assert degraded["outcome"] == "passed"
    assert {m["name"]: m["value"] for m in degraded["metrics"]}["first_audio_frame"] is None
    assert checks["session.cleanup"]["status"] == "PASS"


def test_failed_starts_timeouts_and_interruptions_are_reported_and_reclaimed(
    tmp_path: Path,
    chain: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    path = configuration(tmp_path)
    # A runner that cannot start blocks the session, which is reported at that runner.
    chain.runners["voice"] = (FailingInitRunner, doubles.SpeechRunner)
    code, checks = doctor(capsys, str(path))
    runners = {r["method"]: r["status"] for r in checks["models.runners"]["runners"]}
    assert runners[FailingInitRunner.INFERENCE_METHOD] == "FAIL"
    assert set(runners.values()) == {"FAIL", "SKIP"}
    assert checks["session.start"]["status"] == "FAIL"
    assert scenarios(checks)["voice_vision", "original"]["outcome"] == "conditions_unmet"
    assert (code, checks["session.cleanup"]["status"]) == (1, "PASS")
    assert "private" not in json.dumps(checks)

    # A start that outlives its deadline is ended there, and its process reclaimed.
    chain.runners["voice"] = (doubles.StuckRunner, doubles.SpeechRunner)
    monkeypatch.setattr(doctor_session, "SESSION_SECONDS", 1.0)
    _, checks = doctor(capsys, str(path))
    assert checks["models.runners"]["details"] == ["the runners did not start within 1 s"]
    assert (checks["session.start"]["status"], checks["session.cleanup"]["status"]) == (
        "FAIL",
        "PASS",
    )
    monkeypatch.setattr(doctor_session, "SESSION_SECONDS", 180.0)

    # A turn that outlives its deadline is ended, reported and closed like any other.
    chain.runners["voice"] = (doubles.SpeechRunner,)
    monkeypatch.setattr(doctor_session, "TURN_SECONDS", 0.3)
    _, checks = doctor(capsys, str(path))
    timed_out = scenarios(checks)["voice_vision", "original"]
    assert timed_out["outcome"] == "failed" and "Ended by timeout" in timed_out["details"]
    assert checks["session.cleanup"]["status"] == "PASS"

    # Ctrl+C during the spoken turn: what runs is closed, the rest is reported as not run.
    monkeypatch.setattr(doctor_session, "TURN_SECONDS", 60.0)
    chain.stt.transcripts[:] = [CARD]

    def interrupt() -> None:
        deadline = time.monotonic() + 30
        while chain.stt.transcripts and time.monotonic() < deadline:
            time.sleep(0.002)  # The spoken segment has been committed to STT.
        os.kill(os.getpid(), signal.SIGINT)

    thread = threading.Thread(target=interrupt)
    thread.start()
    try:
        code, checks = doctor(capsys, str(path))
    finally:
        thread.join()
    found = scenarios(checks)
    assert code == 130
    assert found["voice_vision", "original"]["outcome"] == "interrupted"
    assert found["text", "original"]["outcome"] == "interrupted"
    assert checks["session.cleanup"]["status"] == "PASS"
