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
"""What the diagnosis may start, on which storage, and which turn is its own: pure decisions.

Taken from one configuration snapshot, without starting, loading or contacting anything.
"""

from __future__ import annotations

import json
from pathlib import Path

import doctor_doubles as doubles
import pytest
from config_samples import LOOP, write

# Imported at collection: configuration plugins adjust process variables while importing (O-2).
import alphaavatar.agents.configs  # noqa: F401
from alphaavatar.agents.runtime.inference import bootstrap, plan_inference_runners
from alphaavatar.core.log.trace import InputTrace
from alphaavatar.host.configs import load_application
from alphaavatar.host.doctor import samples, session
from alphaavatar.host.doctor.doctor import _external
from alphaavatar.host.doctor.transport import LogRecord, SourceTimeline


def load(tmp_path: Path, **sections: object):
    value = {"application": {"home": str(tmp_path / "home")}, "avatar": {"id": "isolated"}}
    return load_application(write(tmp_path / "avatar.json", value | {"loop": LOOP} | sections))


def test_local_stores_move_into_the_workspace_and_remote_ones_are_never_written(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real" / "memory"
    config = load(
        tmp_path,
        memory={"vdb_config": {"client_path": str(real)}},
        persona={"vdb_config": {"url": "https://vectors.invalid"}},
        host={"doctor": {"external_services": True}},
    )
    workspace = str(tmp_path / "doctor" / "workspace")
    derived, rebound = session.isolate(config, workspace)
    assert rebound == ("memory's LanceDB path",)
    moved = Path(derived.avatar.memory.vdb_config["client_path"])
    assert moved == Path(workspace) / "data" / "indexes" / "memory" / "lancedb"
    assert str(derived.workspace.root) == workspace and not real.exists()
    # Only Doctor's storage changed: the rest is the snapshot that was authorized.
    before, after = json.loads(config.payload), json.loads(derived.payload)
    for data in (before, after):
        data["avatar"].pop("workspace_root")
        data["memory"]["vdb_config"].pop("client_path")
    assert before == after
    # A remote store holds real Avatar data: authorization to call out does not cover it.
    assert session.unisolated(config) == ["persona's Qdrant store"]
    names = [name for name, _ in _external(config)]
    reason = session.blocked(config, names)
    assert reason == "real Avatar data cannot be isolated: persona's Qdrant store"
    assert not session.starts(config, names)


def test_what_doctor_does_not_ship_needs_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = load(tmp_path, memory={"plugin": "custom"}, persona={"plugin": "custom"})
    found = dict(_external(config))
    assert found["custom memory 'custom'"] == "custom"
    names = list(found)
    assert session.blocked(config, names).startswith("not authorized: ")
    # A runner from elsewhere may reach anything while it starts: not started unauthorized.
    voice = {"vad": {"plugin": "silero"}, "stt": {"plugin": None}, "tts": {"plugin": None}}
    router = {"init_config": {"turn_taking": {"enabled": False}}}
    config = load(
        tmp_path,
        voice=voice,
        router=router,
        **{k: {"plugin": "custom"} for k in ("memory", "persona")},
    )
    assert session.starts(config, names)  # Silero alone starts offline, unauthorized.
    monkeypatch.setitem(
        bootstrap._runner_bootstraps, "alphaavatar.plugins.voice", lambda c: (doubles.SpeechRunner,)
    )
    assert session.start_services(config) == [
        "custom runners (alphaavatar.voice.vad.silero), external access unknown"
    ]
    assert not session.starts(config, names)


def test_vision_off_is_a_camera_less_device_and_drops_what_only_vision_needs(
    tmp_path: Path,
) -> None:
    from alphaavatar.plugins.persona.processors.face.analysis_runner import FaceAnalysisRunner

    config = load(tmp_path, vision={"enabled": True, "input_mode": "vlm"})
    without = session.vision_off(config)
    assert not without.avatar.vision.enabled
    assert without.avatar.router.init_config["addressing"]["visual"]["enabled"] is False
    vision_only = set(plan_inference_runners(config.avatar)) - set(
        plan_inference_runners(without.avatar)
    )
    assert vision_only == {FaceAnalysisRunner.INFERENCE_METHOD}

    # Settings of the runner only vision used go with it; those still planned stay.
    kept = next(iter(set(plan_inference_runners(config.avatar)) - vision_only))
    methods = {FaceAnalysisRunner.INFERENCE_METHOD: {"workers": 1}, kept: {"workers": 1}}
    tuned = load(
        tmp_path,
        vision={"enabled": True, "input_mode": "vlm"},
        runtime={"inference": {"methods": methods}},
    )
    without = session.vision_off(tuned)
    assert set(without.avatar.runtime.inference.methods) == {kept}
    assert set(tuned.avatar.runtime.inference.methods) == set(methods)


def test_a_turn_is_the_one_whose_cutoff_covers_this_input_in_this_session() -> None:
    trace = InputTrace()
    for turn, start, end in (("stale", 0, 10), ("other", 10, 20), ("ours", 20, 30)):
        trace.record(
            "turn.committed", turn_id=turn, start_cutoff_sequence=start, cutoff_sequence=end
        )

    def committed(turn: str, session_id: str = "s", text: str = "") -> LogRecord:
        return LogRecord(0, "input.committed", {"session_id": session_id, "turn_id": turn}, text)

    # The frame with the last voiced sample is event 25: only one Turn's range holds it.
    spoken = SourceTimeline(voiced_end_sequence=25)
    logs = [
        committed("ours", "elsewhere"),
        committed("stale"),
        committed("other"),
        committed("ours"),
    ]
    assert session._find_turn(samples.VOICE, "s", logs, trace, 0, spoken) == "ours"
    assert session._find_turn(samples.VOICE, "s", logs[:3], trace, 0, spoken) is None
    assert session._find_turn(samples.VOICE, "s", logs, trace, 0, SourceTimeline()) is None
    # A typed turn commits this very text after the turn began.
    typed = samples.TEXT.text
    logs = [
        committed("stale", text=typed),
        committed("ours", text="else"),
        committed("other", text=typed),
    ]
    assert session._find_turn(samples.TEXT, "s", logs, trace, 12, None) == "other"
    assert session._find_turn(samples.TEXT, "s", logs, trace, 25, None) is None
