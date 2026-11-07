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

# Imported at collection: the persona plugin's OpenCV adjusts process variables (O-2).
import alphaavatar.plugins.persona.factory  # noqa: F401
from alphaavatar.agents.runtime.plugin import AvatarModule
from alphaavatar.core.log.trace import InputTrace
from alphaavatar.host.configs import load_application
from alphaavatar.host.doctor import samples, session
from alphaavatar.host.doctor.doctor import _external
from alphaavatar.host.doctor.transport import LogRecord, SourceTimeline

THIRD_PARTY = Path(__file__).parents[1] / "fixtures" / "thirdparty"


# A voice session, as Doctor's spoken scenarios need.
VOICE = {
    "vad": {"plugin": "silero"},
    "stt": {"plugin": "openai_segment", "model": "m"},
    "tts": {"plugin": "openai", "model": "m", "speaker": "ash"},
}


def load(tmp_path: Path, **sections: object):
    value = {"application": {"home": str(tmp_path / "home")}, "avatar": {"id": "isolated"}}
    value |= {"loop": LOOP, "voice": VOICE}
    return load_application(write(tmp_path / "avatar.json", value | sections))


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


def test_nothing_starts_unauthorized_whatever_its_runners_and_their_calls_are_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alphaavatar.plugins.voice.vad import SileroVADPlugin

    doubles.resolvable(
        monkeypatch, (AvatarModule.MEMORY, "custom"), (AvatarModule.PERSONA, "custom")
    )
    router = {"init_config": {"turn_taking": {"enabled": False}}}
    config = load(
        tmp_path, router=router, **{k: {"plugin": "custom"} for k in ("memory", "persona")}
    )
    found = dict(_external(config))
    assert found["custom memory 'custom'"] == "custom"
    names = list(found)
    assert session.blocked(config, names).startswith("not authorized: ")
    # Silero alone, a stand-in, or a third-party runner in the plugins' own namespace: none
    # starts before the diagnosis is authorized, its module path vouching for nothing.
    monkeypatch.syspath_prepend(str(THIRD_PARTY))
    from alphaavatar.plugins.doctor_thirdparty.runner import ThirdPartyRunner

    for runner in (None, doubles.SpeechRunner, ThirdPartyRunner):
        if runner is not None:
            monkeypatch.setattr(
                SileroVADPlugin, "inference_runners", lambda self, config, r=runner: (r,)
            )
        assert not session.starts(config, names)
        assert session.starts(
            session.derive(config, {"host.doctor.external_services": True}), names
        )
    # What runners say they call as they start is listed for the one question: a vector
    # store's embeddings, by the runner that sends its probe.
    assert session.start_services(config) == []
    stores = load(tmp_path)
    assert "embeddings as alphaavatar.memory.vdb.lancedb starts" in session.start_services(stores)


def test_a_remote_store_blocks_the_diagnosis_unless_the_configuration_names_it_a_test_store(
    tmp_path: Path,
) -> None:
    qdrant = {"vdb_config": {"url": "http://qdrant.invalid:6333"}}
    config = load(tmp_path, memory=qdrant, host={"doctor": {"external_services": True}})
    assert session.unisolated(config) == ["memory's Qdrant store"]
    assert session.blocked(config, []).startswith("real Avatar data cannot be isolated")
    # Named a test store: written by the diagnosis, and said so in its report.
    tested = session.derive(config, {"host.doctor.test_stores": True})
    assert session.unisolated(tested) == [] and session.blocked(tested, []) is None
    assert session.remote_stores(tested) == ["memory's Qdrant store"]


def test_the_plan_is_one_spoken_scenario_by_vision_and_none_without_voice(tmp_path: Path) -> None:
    seen = session.plan(load(tmp_path, vision={"enabled": True, "input_mode": "vlm"}))
    assert (seen.tasks, seen.session_type) == ((samples.VOICE_VISION,), "video")
    assert seen.configuration.endswith("vision vlm, max_frames 4")
    # Vision off, or frames as text: the two-sentence question, on audio alone.
    for vision in ({"enabled": False}, {"enabled": True, "input_mode": "text"}):
        blind = session.plan(load(tmp_path, vision=vision))
        assert (blind.tasks, blind.session_type, blind.missing) == ((samples.VOICE,), "audio", None)
        assert blind.configuration.endswith("vision off")
    # A voice session needs all three; without them there is nothing to run, and why.
    mute = load(tmp_path, voice=VOICE | {"tts": {"plugin": None}})
    assert session.plan(mute).tasks == ()
    assert session.plan(mute).missing.endswith("this configuration has no voice.tts")
    assert session.blocked(mute, []).startswith("no scenario to run: its scenarios are spoken")


def test_a_turn_is_the_one_whose_cutoff_covers_this_input_in_this_session() -> None:
    trace = InputTrace()
    for turn, start, end in (("stale", 0, 10), ("other", 10, 20), ("ours", 20, 30)):
        trace.record(
            "turn.committed", turn_id=turn, start_cutoff_sequence=start, cutoff_sequence=end
        )

    def committed(turn: str, session_id: str = "s") -> LogRecord:
        return LogRecord(0, "input.committed", {"session_id": session_id, "turn_id": turn})

    # The frame with the last voiced sample is event 25: only one Turn's range holds it.
    spoken = SourceTimeline(voiced_end_sequence=25)
    logs = [
        committed("ours", "elsewhere"),
        committed("stale"),
        committed("other"),
        committed("ours"),
    ]
    assert session._find_turn("s", logs, trace, spoken) == "ours"
    assert session._find_turn("s", logs[:3], trace, spoken) is None
    assert session._find_turn("s", logs, trace, SourceTimeline()) is None
