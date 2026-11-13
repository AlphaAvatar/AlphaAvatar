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
"""Face/Speaker evidence stays with its Participant; late inference never rebinds identity."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from collections.abc import Callable
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import alphaavatar.plugins.persona  # noqa: F401  Registers the default Persona plugin.
from alphaavatar.agents.runtime import AvatarRuntime, StateRuntime
from alphaavatar.agents.runtime.modules.participants import ParticipantRuntime
from alphaavatar.agents.runtime.plugin import AvatarModule, AvatarModulePlugin
from alphaavatar.agents.workspace import WorkspacePaths, prepare_session_path, prepare_workspace
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.env.enums import ObservationKind
from alphaavatar.core.env.schemas import (
    PerceptionEntityRef,
    PerceptionSegmentRef,
    PerceptionSourceRef,
)
from alphaavatar.core.media import (
    AudioFrame,
    AudioFramePayload,
    AudioSegmentPayload,
    VideoFramePayload,
)
from alphaavatar.core.media.enums import PayloadFormat, PayloadView
from alphaavatar.core.output import OutputRuntime
from alphaavatar.core.perception import PerceptionRuntime
from alphaavatar.core.perception.enums import PerceptionStreamKind
from alphaavatar.core.session import SessionRuntime
from alphaavatar.core.session.enums import IdentityOutcome, IdentitySource
from alphaavatar.core.session.schemas import IdentityRequest
from alphaavatar.core.time import RuntimeTimeRange
from alphaavatar.core.turn import TurnRuntime
from alphaavatar.core.turn.enums import TurnInputModality
from alphaavatar.plugins.persona.processors.face.analysis_runner import FaceAnalysisRunner
from alphaavatar.plugins.persona.processors.speaker.attribute_runner import SpeakerAttributeRunner
from alphaavatar.plugins.persona.processors.speaker.processor import SpeakerProcessor
from alphaavatar.plugins.persona.processors.speaker.tracking import SpeakerTracks
from alphaavatar.plugins.persona.processors.speaker.vector_runner import SpeakerVectorRunner

HANG_GUARD = 30
VDB = "alphaavatar.persona.vdb.lancedb"
PEOPLE = ("alice", "bob", "carol")  # Each a vector of its own
USERS = PEOPLE[:2]
# Constant PCM levels identify each physical speaker's audio inside the offline model double.
LEVELS = {8192: "alice", 16384: "bob", 24576: "carol"}
# The Persona VDB runner answers a miss with no result, or with a row that has no user; or
# it matches another stored user above the threshold.
SEARCH_REPLIES = {
    "none": None,
    "empty-user": {"user_id": "", "score": 0.99},
    "wrong": {"user_id": "mallory"},
}


def embedding(user: str, size: int) -> np.ndarray:
    vector = np.zeros(size, dtype=np.float32)
    vector[PEOPLE.index(user)] = 1.0
    return vector


class SensorInference:
    """Offline Face/Speaker models and Persona VDB; one model request can be held open."""

    def __init__(self) -> None:
        self.searches: list[str] = []
        self.hold: str | None = None
        self.fail: str | None = None  # A user whose speaker vector request fails
        self.held, self.release = asyncio.Event(), asyncio.Event()
        # Vector searches answer in order: "matched" or a SEARCH_REPLIES miss.
        self.replies: deque[str] = deque()
        self.hold_search = False
        self.search_held, self.search_release = asyncio.Event(), asyncio.Event()
        self.attribute_delay = 0.0  # A speaker attribute inference that takes its time
        self.hold_attribute = False
        self.attribute_held, self.attribute_release = asyncio.Event(), asyncio.Event()
        self.attributes: list[str] = []  # Whose speech each attribute inference heard
        self.attribute_samples: list[int] = []
        self.vector_samples: list[int] = []  # The length of each speaker vector request
        self.voices: deque[np.ndarray] = deque()  # Speaker vectors to answer first, in order
        self.saves: list[str] = []

    async def _maybe_hold(self, user: str) -> None:
        if user == self.hold:
            self.hold = None
            self.held.set()
            await self.release.wait()

    async def do_inference(self, method: str, data: bytes) -> bytes | None:
        if method == SpeakerVectorRunner.INFERENCE_METHOD:
            self.vector_samples.append(len(data) // 4)
            user = LEVELS[round(np.frombuffer(data, dtype=np.float32)[0] * 32768)]
            if user == self.fail:
                raise RuntimeError("speaker vector runner failed")
            await self._maybe_hold(user)
            voice = self.voices.popleft() if self.voices else embedding(user, 192)
            return voice.astype(np.float32).tobytes()
        if method == SpeakerAttributeRunner.INFERENCE_METHOD:
            self.attributes.append(LEVELS[round(np.frombuffer(data, dtype=np.float32)[0] * 32768)])
            self.attribute_samples.append(len(data) // 4)
            if self.hold_attribute:
                self.hold_attribute = False
                self.attribute_held.set()
                await self.attribute_release.wait()
            await asyncio.sleep(self.attribute_delay)
            attributes = {
                "logits_age": np.array([[0.3]], dtype=np.float32),
                "logits_gender": np.array([[0.0, 9.0, 0.0]], dtype=np.float32),
            }
            return json.dumps(attributes, default=SpeakerAttributeRunner._json_numpy).encode()
        if method == FaceAnalysisRunner.INFERENCE_METHOD:
            users = data.decode().split("+")
            for user in users:
                await self._maybe_hold(user)
            faces = [
                {
                    "bbox": [100.0 * index, 0.0, 100.0 * index + 90, 90.0],
                    "det_score": 0.9,
                    "embedding": embedding(user, 512).tolist(),
                    "entity": {"entity_id": f"face-{user}"},
                    "age": 30 + 20 * index,
                    "gender": "F" if user == "alice" else "M",
                }
                for index, user in enumerate(users)
            ]
            return json.dumps({"faces": faces, "image_width": 640, "image_height": 480}).encode()
        assert method == VDB
        request = json.loads(data)
        if request["op"] in ("search_speaker_vector", "search_face_vector"):
            kind = request["op"].split("_")[1]
            user = PEOPLE[int(np.argmax(request["param"][f"{kind}_vector"]))]
            self.searches.append(f"{kind}:{user}")
            if self.hold_search:
                self.hold_search = False
                self.search_held.set()
                await self.search_release.wait()
            reply = self.replies.popleft() if self.replies else "matched"
            result = {"user_id": user} if reply == "matched" else SEARCH_REPLIES[reply]
            return None if result is None else json.dumps(result).encode()
        if request["op"] == "load":
            return b'{"details_items":[],"speaker_vector":null,"face_vector":null}'
        self.saves.append(request["param"]["user_id"])
        return b'{"user_id":"x","error":null}'

    async def close(self) -> None:
        pass


def avatar_runtime(root: Path, inference: SensorInference) -> AvatarRuntime:
    workspace = WorkspacePaths.from_root(root / "avatar")
    prepare_workspace(workspace)
    session = SessionRuntime(session_id="session")
    session_path = workspace.data.sessions.get("session", date(2026, 11, 2))
    prepare_session_path(session_path)
    perception = PerceptionRuntime(
        session_id="session",
        stream_maxlens=dict.fromkeys(PerceptionStreamKind, 256),
        clock=session.clock,
    )
    turn = TurnRuntime(perception=perception)
    return AvatarRuntime(
        clock=session.clock,
        workspace=workspace,
        session_path=session_path,
        session=session,
        perception=perception,
        turn=turn,
        output=OutputRuntime(session_id="session", clock=session.clock),
        state=StateRuntime(),
        participants=ParticipantRuntime(session=session, workspace=workspace, turn=turn),
        inference=inference,
    )


def persona_for(runtime: AvatarRuntime, sensor: str, **speaker: object):
    other = "face" if sensor == "speaker" else "speaker"
    return AvatarModulePlugin.create(
        AvatarModule.PERSONA,
        "default",
        runtime=runtime,
        vdb_config={},
        init_config={
            "profiler": {"enabled": False},
            other: {"enabled": False},
            **({"speaker": {"inference_queue_size": 8} | speaker} if sensor == "speaker" else {}),
        },
    )


def speak(
    runtime: AvatarRuntime,
    source: PerceptionSourceRef,
    segment: str,
    user: str,
    *,
    end: bool = True,
    explicit: bool = True,
) -> None:
    """Publish one entity's 3 s utterance: exactly one model window, then the segment end;
    ``explicit``: its subject named on each frame, or known by its voice alone."""
    level = next(level for level, name in LEVELS.items() if name == user)
    pcm = np.full(16000, level, dtype="<i2").tobytes()
    common = {
        "source": source,
        "segment": PerceptionSegmentRef(source, segment),
        "device_id": source.source_id,
        **({"entity": PerceptionEntityRef(f"voice-{user}")} if explicit else {}),
    }
    for index in range(3):
        frame = AudioFrame(sample_rate=16000, num_channels=1, samples_per_channel=16000, data=pcm)
        runtime.perception.publish_observation(
            EnvObservation(
                kind=ObservationKind.SPEECH_FRAME,
                time_range=RuntimeTimeRange.point(runtime.clock.now()),
                payload=AudioFramePayload.create(frame=frame, frame_id=f"{segment}-{index}"),
                **common,
            )
        )
    if end:
        runtime.perception.publish_observation(
            EnvObservation(
                kind=ObservationKind.SPEECH_SEGMENT,
                time_range=RuntimeTimeRange.point(runtime.clock.now()),
                **common,
            )
        )


def utter(
    runtime: AvatarRuntime,
    source: PerceptionSourceRef,
    segment: str,
    user: str,
    *,
    heard: float,
    spoken: float | None,
) -> None:
    """One utterance known by its voice alone: ``heard`` seconds of routed frames, then its end,
    carrying the Router's canonical audio of ``spoken`` seconds (its pre-roll and speech, not
    the trailing silence) or none."""
    level = next(level for level, name in LEVELS.items() if name == user)
    ref = PerceptionSegmentRef(source, segment)
    common = {"source": source, "segment": ref, "device_id": source.source_id}
    samples = round(heard * 16000)
    for index, start in enumerate(range(0, samples, 8000)):
        count = min(8000, samples - start)
        pcm = np.full(count, level, dtype="<i2").tobytes()
        frame = AudioFrame(sample_rate=16000, num_channels=1, samples_per_channel=count, data=pcm)
        runtime.perception.publish_observation(
            EnvObservation(
                kind=ObservationKind.SPEECH_FRAME,
                time_range=RuntimeTimeRange.point(runtime.clock.now()),
                payload=AudioFramePayload.create(frame=frame, frame_id=f"{segment}-{index}"),
                **common,
            )
        )
    payload = None
    if spoken is not None:
        count = round(spoken * 16000)
        payload = AudioSegmentPayload.create(
            segment_id=segment,
            pcm16_bytes=np.full(count, level, dtype="<i2").tobytes(),
            sample_rate=16000,
            num_channels=1,
            samples_per_channel=count,
            source_observation_ids=(f"{segment}-0",),
        )
    now = runtime.clock.now()
    runtime.perception.publish_observation(
        EnvObservation(
            kind=ObservationKind.SPEECH_SEGMENT,
            # Its VAD range: the speech it carries.
            time_range=RuntimeTimeRange(start=now.shifted(-(spoken or 0.0)), end=now),
            payload=payload,
            **common,
        )
    )


def show(
    runtime: AvatarRuntime, source: PerceptionSourceRef, *users: str, later: float = 0.0
) -> None:
    payload = VideoFramePayload(frame_id=None, width=640, height=480)
    payload.put(PayloadFormat.IMAGE_JPEG_BYTES, "+".join(users).encode(), view=PayloadView.RAW)
    runtime.perception.publish_observation(
        EnvObservation(
            kind=ObservationKind.VIDEO_FRAME,
            # A later capture time passes the per-source face sampling interval.
            time_range=RuntimeTimeRange.point(runtime.clock.now().shifted(later)),
            source=source,
            device_id=source.source_id,
            payload=payload,
        )
    )


def observe(runtime: AvatarRuntime, sensor: str, source: PerceptionSourceRef, *users: str) -> None:
    if sensor == "face":
        show(runtime, source, *users)
        return
    for index, user in enumerate(users):
        speak(runtime, PerceptionSourceRef(f"{source.source_id}-{index}", 1), "a", user)


def participant_of(runtime: AvatarRuntime, user: str):
    return next((p for p in runtime.session.participants.values() if p.user_id == user), None)


async def wait_until(condition: Callable[[], bool], failure: str) -> None:
    try:
        async with asyncio.timeout(HANG_GUARD):
            while not condition():
                await asyncio.sleep(0.001)
    except TimeoutError:
        pytest.fail(failure, pytrace=False)


@pytest.mark.parametrize("sensor", ["speaker", "face"])
async def test_sensor_evidence_and_attributes_stay_with_each_participant(
    sensor: str, tmp_path: Path
) -> None:
    inference = SensorInference()
    runtime = avatar_runtime(tmp_path, inference)
    persona = persona_for(runtime, sensor)
    await persona.on_start()
    observe(runtime, sensor, PerceptionSourceRef("device", 1), *USERS)

    def profiled(user: str) -> bool:
        participant = participant_of(runtime, user)
        cache = participant and persona.persona_cache.get(participant.participant_id)
        return bool(cache and cache.profile_details and cache.profile_details.gender)

    await wait_until(lambda: all(map(profiled, USERS)), f"{sensor} evidence was not resolved")
    alice, bob = (participant_of(runtime, user) for user in USERS)
    assert alice.participant_id != bob.participant_id
    size = 192 if sensor == "speaker" else 512
    genders = {"alice": "female", "bob": "female" if sensor == "speaker" else "male"}
    for participant in (alice, bob):
        cache = persona.persona_cache[participant.participant_id]
        vector = cache.speaker_vector if sensor == "speaker" else cache.face_vector
        np.testing.assert_allclose(vector, embedding(participant.user_id, size))
        assert cache.profile_details.gender.value == genders[participant.user_id]
    assert sorted(inference.searches) == [f"{sensor}:alice", f"{sensor}:bob"]
    await persona.on_stop()
    await runtime.aclose()


@pytest.mark.parametrize("explicit", [True, False], ids=["named-subject", "by-voice"])
async def test_the_association_is_ready_when_it_is_known_and_each_step_keeps_its_span(
    explicit: bool, tmp_path: Path
) -> None:
    runtime = avatar_runtime(tmp_path, SensorInference())
    persona = persona_for(runtime, "speaker")
    await persona.on_start()
    speak(runtime, PerceptionSourceRef("device", 1), "a", "alice", explicit=explicit)

    def records(stage: str) -> list[dict]:
        found = runtime.perception.input_trace.snapshot().to_dict()["records"]
        return [record for record in found if record["stage"] == stage]

    await wait_until(lambda: records("speaker.attribute"), "the speaker was never profiled")
    (window,) = records("speaker.window")
    (settled,) = records("participant.segment_ready")  # Once: no later unbound
    assert (window["sequence"], window["outcome"], settled["outcome"]) == (1, "done", "bound")
    assert window["event_time_ns"] <= window["start_time_ns"] <= window["end_time_ns"]
    if explicit:
        # Its subject came with its first frame: bound then, before any window ran.
        assert settled["end_time_ns"] <= window["start_time_ns"]
    else:
        # Known by its voice alone: ready once the window that gave it was done.
        assert settled["end_time_ns"] >= window["end_time_ns"]
    # The identity match and the attributes follow the association, on a lane of their own.
    (identity,) = records("speaker.identity")
    (attribute,) = records("speaker.attribute")
    assert settled["end_time_ns"] <= identity["start_time_ns"] <= identity["end_time_ns"]
    assert identity["end_time_ns"] <= attribute["start_time_ns"] <= attribute["end_time_ns"]
    assert {identity["outcome"], attribute["outcome"]} == {"done"}
    await persona.on_stop()
    await runtime.aclose()


@pytest.mark.parametrize("ending", ["timeout", "failed"])
async def test_a_window_that_times_out_or_fails_releases_its_association_and_says_so(
    ending: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    from alphaavatar.plugins.persona.processors.speaker import model_files

    key = SpeakerVectorRunner.MODEL_TYPE
    vector = replace(model_files.SPEAKER_MODEL_CONFIG[key], inference_timeout_sec=0.1)
    monkeypatch.setitem(model_files.SPEAKER_MODEL_CONFIG, key, vector)
    inference = SensorInference()
    if ending == "timeout":
        inference.hold = "alice"  # Never released: the request outlives its bound.
    else:
        inference.fail = "alice"
    runtime = avatar_runtime(tmp_path, inference)
    persona = persona_for(runtime, "speaker")
    await persona.on_start()
    speak(runtime, PerceptionSourceRef("device", 1), "a", "alice", explicit=False)

    def records(stage: str) -> list[dict]:
        found = runtime.perception.input_trace.snapshot().to_dict()["records"]
        return [record for record in found if record["stage"] == stage]

    await wait_until(lambda: records("participant.segment_ready"), "the association was held")
    (window,) = records("speaker.window")
    (settled,) = records("participant.segment_ready")
    # Known by its voice alone, which the window never gave: released unbound, at once after
    # the window ended, its ending said; a commit waiting on it waits no longer.
    assert (window["outcome"], settled["outcome"]) == (ending, "unbound")
    assert window["end_time_ns"] <= settled["end_time_ns"] <= window["end_time_ns"] + 50_000_000
    if ending == "timeout":
        assert window["end_time_ns"] - window["start_time_ns"] >= 100_000_000
    inference.release.set()
    await persona.on_stop()
    await runtime.aclose()


def settled(runtime: AvatarRuntime, count: int) -> Callable[[], bool]:
    return lambda: len(traced(runtime, "participant.segment_ready")) >= count


@pytest.mark.parametrize(
    ("heard", "spoken", "jobs"),
    [(1.5, 1.2, [19200]), (3.0, 2.6, [48000]), (3.5, 3.2, [48000, 48000]), (1.5, None, [])],
    ids=["short", "one-window", "window-and-tail", "no-segment-audio"],
)
async def test_speech_shorter_than_a_window_is_inferred_once_at_its_own_length(
    heard: float,
    spoken: float | None,
    jobs: list[int],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Speech that never filled a window gives one vector of the segment's own audio, never
    # padded; speech that did keeps its windows and full tail and gets no shorter copy.
    monkeypatch.setattr(SpeakerProcessor, "ATTRIBUTE_INTERVAL_SEC", 0.0)  # Every segment is due
    inference = SensorInference()
    runtime = avatar_runtime(tmp_path, inference)
    persona = persona_for(runtime, "speaker")
    await persona.on_start()
    source = PerceptionSourceRef("device", 1)
    # A full window opens alice's voice, the utterance under test follows, then another window.
    for count, (segment, length, audio) in enumerate(
        (("a", 3.0, 2.6), ("b", heard, spoken), ("c", 3.0, 2.6)), 1
    ):
        utter(runtime, source, segment, "alice", heard=length, spoken=audio)
        await wait_until(settled(runtime, count), f"segment {segment} was never settled")
    windows = 2 + (48000 in jobs)
    await wait_until(lambda: len(inference.searches) == 2 + bool(jobs), "a search never ran")
    await wait_until(
        lambda: len(inference.attributes) >= windows, "the speaker was never described"
    )
    assert inference.vector_samples == [48000, *jobs, 48000]
    assert inference.searches == ["speaker:alice"] * (2 + bool(jobs))
    # The attribute model keeps its own input: full windows only, never the short audio.
    assert inference.attribute_samples == [48000] * windows
    await persona.on_stop()
    await runtime.aclose()


async def test_a_frame_published_again_counts_once_until_it_is_forgotten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The Router can publish a routed frame again: a segment counts it once, remembering only
    # its last MAX_SEEN_OBSERVATIONS frames, the oldest forgotten first.
    monkeypatch.setattr(SpeakerProcessor, "MAX_SEEN_OBSERVATIONS", 2)
    inference = SensorInference()
    runtime = avatar_runtime(tmp_path, inference)
    persona = persona_for(runtime, "speaker")
    await persona.on_start()
    source = PerceptionSourceRef("device", 1)
    common = {
        "source": source,
        "segment": PerceptionSegmentRef(source, "a"),
        "device_id": source.source_id,
    }
    pcm = np.full(16000, 8192, dtype="<i2").tobytes()  # 1 s of alice
    # r2 is still remembered when it comes again; r1 has been forgotten, so it counts again.
    for index, routed in enumerate(("r1", "r2", "r3", "r2", "r1")):
        frame = AudioFrame(sample_rate=16000, num_channels=1, samples_per_channel=16000, data=pcm)
        runtime.perception.publish_observation(
            EnvObservation(
                kind=ObservationKind.SPEECH_FRAME,
                time_range=RuntimeTimeRange.point(runtime.clock.now()),
                payload=AudioFramePayload.create(frame=frame, frame_id=f"a-{index}"),
                metadata={"source_observation_id": routed},
                **common,
            )
        )
    runtime.perception.publish_observation(
        EnvObservation(
            kind=ObservationKind.SPEECH_SEGMENT,
            time_range=RuntimeTimeRange.point(runtime.clock.now()),
            **common,
        )
    )
    await wait_until(lambda: inference.searches, "the segment was never searched")

    # 4 s counted: a window at 3 s and the next at 4 s, which leaves no tail.
    assert inference.vector_samples == [48000, 48000]
    await persona.on_stop()
    await runtime.aclose()


@pytest.mark.parametrize("case", ["registered", "unregistered", "mismatched", "reconnected"])
async def test_short_utterances_from_a_sessions_start_open_a_voice_and_are_identified(
    case: str, tmp_path: Path
) -> None:
    # No named subject and no voice yet: each 1-2 s utterance gets its own vector, opens or
    # continues a track and is searched like any other; the search decides the identity.
    inference = SensorInference()
    reply = {"registered": "matched", "unregistered": "none", "mismatched": "wrong"}.get(case)
    runtime = avatar_runtime(tmp_path, inference)
    persona = persona_for(runtime, "speaker")
    await persona.on_start()
    source = PerceptionSourceRef("device", 1)
    if case == "reconnected":
        # Known on the first connection; the new generation keeps its voice.
        utter(runtime, source, "before", "alice", heard=3.0, spoken=2.6)
        await wait_until(lambda: participant_of(runtime, "alice"), "alice was never identified")
        await wait_until(lambda: inference.attribute_samples, "alice was never described")
        before = participant_of(runtime, "alice")
        source = PerceptionSourceRef("device", 2)
        inference.vector_samples.clear()
        inference.searches.clear()
    lengths = (1.2, 1.8, 1.0)
    for index, length in enumerate(lengths):
        if reply is not None:
            inference.replies.append(reply)
        utter(runtime, source, f"short-{index}", "alice", heard=length + 0.3, spoken=length)
        await wait_until(
            lambda index=index: len(inference.searches) == index + 1,
            f"short utterance {index} was never searched",
        )

    assert inference.vector_samples == [round(length * 16000) for length in lengths]
    assert inference.searches == ["speaker:alice"] * len(lengths)
    (participant_id,) = {
        runtime.participants.resolve(
            segment=PerceptionSegmentRef(source, f"short-{index}")
        ).participant_id
        for index in range(len(lengths))
    }  # One voice: every utterance is attributed to the same participant.
    current = runtime.participants.get(participant_id)
    generated = runtime.session.get_identity(participant_id, 0)
    if case == "unregistered":
        # No match: a new voice keeps its generated user, never someone else's.
        assert current == generated and participant_of(runtime, "alice") is None
    else:
        expected = "mallory" if case == "mismatched" else "alice"
        # The match binds what the search found: right, or wrong on wrong evidence.
        assert (current.user_id, current.identity_revision) == (expected, 1)
    if case == "reconnected":
        assert participant_id == before.participant_id
    # The attribute model never hears the short audio.
    assert inference.attribute_samples == ([48000] if case == "reconnected" else [])
    await persona.on_stop()
    await runtime.aclose()


@pytest.mark.parametrize(
    ("margin", "query", "joined"),
    [(0.0, (1.0, 1.0), False), (0.05, (1.0, 0.95), False), (0.05, (1.0, 0.9), True)],
    ids=["tie", "within-margin", "beyond-margin"],
)
def test_a_voice_as_close_to_two_tracks_as_the_margin_joins_neither(
    margin: float, query: tuple[float, float], joined: bool
) -> None:
    source = PerceptionSourceRef("device", 1)
    tracks = SpeakerTracks(threshold=0.6, margin=margin)
    first = tracks.resolve(source, np.array([1.0, 0.0, 0.0]), 3.0)
    assert tracks.resolve(source, np.array([0.0, 1.0, 0.0]), 3.0) not in (None, first)
    vector = np.array([*query, 0.0]) / np.linalg.norm([*query, 0.0])
    # Both tracks are above the threshold; the closer one only when it is clear of the other.
    assert tracks.resolve(source, vector, 3.0) == (first if joined else None)
    # A single candidate needs only the threshold.
    alone = SpeakerTracks(threshold=0.6, margin=margin)
    only = alone.resolve(source, np.array([1.0, 0.0, 0.0]), 3.0)
    assert alone.resolve(source, vector, 3.0) == only


def test_a_track_is_one_voice_on_every_source_and_generation_it_is_heard_on() -> None:
    tracks = SpeakerTracks(threshold=0.6, margin=0.0)
    voice = np.array([1.0, 0.0, 0.0])
    first, later = PerceptionSourceRef("device", 1), PerceptionSourceRef("device", 2)
    laptop = PerceptionSourceRef("laptop", 1)
    entity = tracks.resolve(first, voice, 3.0)
    assert [tracks.resolve(source, voice, 3.0) for source in (later, laptop, first)] == [entity] * 3

    # Every source and generation it was heard on, in order: a new generation replaces none.
    (track,) = tracks._tracks.values()
    assert track.sources == [first, later, laptop]
    assert tracks.drain_retired() == ()
    tracks.clear()
    assert tracks.drain_retired() == (entity,)


async def test_one_voice_is_one_participant_across_devices_and_a_cancelled_source(
    tmp_path: Path,
) -> None:
    inference = SensorInference()
    inference.replies.extend(["none"] * 3)  # A new user: only its voice holds it together
    runtime = avatar_runtime(tmp_path, inference)
    persona = persona_for(runtime, "speaker")
    await persona.on_start()
    phone, laptop, again = (
        PerceptionSourceRef("device", 1),
        PerceptionSourceRef("laptop", 1),
        PerceptionSourceRef("device", 2),
    )
    utter(runtime, phone, "u0", "alice", heard=3.0, spoken=2.6)
    await wait_until(
        lambda: len(inference.searches) == 1, "the phone's utterance was never searched"
    )
    first = runtime.participants.resolve(segment=PerceptionSegmentRef(phone, "u0"))
    utter(runtime, laptop, "u1", "alice", heard=3.0, spoken=2.6)
    await wait_until(
        lambda: len(inference.searches) == 2, "the laptop's utterance was never searched"
    )
    # The phone's source is cancelled while it speaks; it comes back as a new generation.
    speak(runtime, phone, "open", "alice", end=False, explicit=False)
    runtime.perception.publish_observation(
        EnvObservation(
            kind=ObservationKind.SPEECH_CANCELLED,
            time_range=RuntimeTimeRange.point(runtime.clock.now()),
            source=phone,
            segment=PerceptionSegmentRef(phone, "open"),
            metadata={"reason_code": "source_ended"},
        )
    )
    utter(runtime, again, "u2", "alice", heard=3.0, spoken=2.6)
    await wait_until(lambda: len(inference.searches) == 3, "the new generation was never searched")

    heard = [
        runtime.participants.resolve(segment=PerceptionSegmentRef(source, name))
        for source, name in ((laptop, "u1"), (again, "u2"))
    ]
    assert first is not None and heard == [first, first]  # One participant, one generated user
    await persona.on_stop()
    await runtime.aclose()


async def test_a_segment_in_flight_when_its_voice_is_identified_still_takes_its_identity_step(
    tmp_path: Path,
) -> None:
    inference = SensorInference()
    inference.hold_search = True  # The first segment's search, held while the next one begins
    runtime = avatar_runtime(tmp_path, inference)
    persona = persona_for(runtime, "speaker")
    await persona.on_start()
    speaker = next(processor for processor in persona._processors if processor.name == "speaker")
    source = PerceptionSourceRef("device", 1)
    utter(runtime, source, "first", "alice", heard=3.0, spoken=2.6)
    async with asyncio.timeout(HANG_GUARD):
        await inference.search_held.wait()
    speak(runtime, source, "next", "alice", end=False, explicit=False)
    await wait_until(
        lambda: PerceptionSegmentRef(source, "next") in speaker._segments, "it never began"
    )
    # The first identifies the voice: its participant takes a new identity version.
    inference.search_release.set()
    await wait_until(lambda: participant_of(runtime, "alice"), "the first was never identified")
    runtime.perception.publish_observation(
        EnvObservation(
            kind=ObservationKind.SPEECH_SEGMENT,
            time_range=RuntimeTimeRange.point(runtime.clock.now()),
            source=source,
            segment=PerceptionSegmentRef(source, "next"),
            device_id=source.source_id,
        )
    )

    # The segment begun before it is searched all the same, as that participant now.
    await wait_until(lambda: len(inference.searches) == 2, "the next segment was never searched")
    alice = participant_of(runtime, "alice")
    assert runtime.participants.resolve(segment=PerceptionSegmentRef(source, "next")) == alice
    await persona.on_stop()
    await runtime.aclose()


async def test_a_segment_begun_before_its_voice_had_a_participant_is_still_identified(
    tmp_path: Path,
) -> None:
    inference = SensorInference()
    runtime = avatar_runtime(tmp_path, inference)
    persona = persona_for(runtime, "speaker")
    await persona.on_start()
    phone, laptop = PerceptionSourceRef("phone", 1), PerceptionSourceRef("laptop", 1)
    # The laptop begins to hear a new voice; the phone's segment of it ends first and makes
    # its participant, after the laptop's segment began.
    speak(runtime, laptop, "b", "alice", end=False, explicit=False)
    utter(runtime, phone, "a", "alice", heard=3.0, spoken=2.6)
    await wait_until(lambda: len(inference.searches) == 1, "the phone's segment was never searched")
    runtime.perception.publish_observation(
        EnvObservation(
            kind=ObservationKind.SPEECH_SEGMENT,
            time_range=RuntimeTimeRange.point(runtime.clock.now()),
            source=laptop,
            segment=PerceptionSegmentRef(laptop, "b"),
            device_id=laptop.source_id,
        )
    )

    # The laptop's segment is searched with its own vector too, as that same participant.
    await wait_until(lambda: len(inference.searches) == 2, "the laptop's segment never searched")
    heard = [
        runtime.participants.resolve(segment=PerceptionSegmentRef(source, name))
        for source, name in ((phone, "a"), (laptop, "b"))
    ]
    assert heard[0] is not None and heard == [heard[0]] * 2
    await persona.on_stop()
    await runtime.aclose()


async def test_a_new_users_voice_silent_for_an_hour_is_still_one_participant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alphaavatar.plugins.persona.processors.speaker import processor as speaker_processor

    inference = SensorInference()
    inference.replies.extend(["none"] * 2)  # A new user: no stored voice to find it again
    runtime = avatar_runtime(tmp_path, inference)
    persona = persona_for(runtime, "speaker")
    await persona.on_start()
    source = PerceptionSourceRef("device", 1)
    utter(runtime, source, "before", "alice", heard=3.0, spoken=2.6)
    await wait_until(lambda: len(inference.searches) == 1, "the first utterance was never searched")
    before = runtime.participants.resolve(segment=PerceptionSegmentRef(source, "before"))

    # An hour later on the processor's clock, the same voice on the same source generation.
    real = time.monotonic
    monkeypatch.setattr(speaker_processor, "time", SimpleNamespace(monotonic=lambda: real() + 3600))
    utter(runtime, source, "after", "alice", heard=3.0, spoken=2.6)
    await wait_until(
        lambda: len(inference.searches) == 2, "the second utterance was never searched"
    )

    # Its track held: the same participant and generated user, not a second one.
    after = runtime.participants.resolve(segment=PerceptionSegmentRef(source, "after"))
    assert before is not None and after == before
    await persona.on_stop()
    await runtime.aclose()


def test_short_merge_must_cover_a_short_segment() -> None:
    from alphaavatar.plugins.persona.processors.speaker.config import SpeakerConfig

    assert SpeakerConfig(short_segment_sec=1.0, short_merge_sec=1.0).short_merge_sec == 1.0
    with pytest.raises(ValueError, match="short_merge_sec cannot be smaller"):
        SpeakerConfig(short_segment_sec=1.5, short_merge_sec=1.0)


async def test_short_segments_are_inferred_together_once_long_enough_and_never_waited_on(
    tmp_path: Path,
) -> None:
    inference = SensorInference()
    inference.hold_search = True  # The search of their audio is held: no Turn may wait on it
    runtime = avatar_runtime(tmp_path, inference)
    persona = persona_for(runtime, "speaker", identity_wait_sec=5.0)
    await persona.on_start()
    source = PerceptionSourceRef("device", 1)
    for index, spoken in enumerate((0.8, 0.7, 0.6)):
        utter(runtime, source, f"short-{index}", "alice", heard=spoken + 0.2, spoken=spoken)
    async with asyncio.timeout(HANG_GUARD):
        await inference.search_held.wait()

    # One vector of all three, 0.8 + 0.7 + 0.6 s, once together they reach 2 s.
    assert inference.vector_samples == [33600]
    # Each Turn of short speech goes on at once, never at the 5 s identity bound.
    for index in range(3):
        ready = runtime.turn.wait_context_ready(spoken_turn(runtime, f"short-{index}"))
        assert await asyncio.wait_for(ready, 1) is True
    inference.search_release.set()
    await wait_until(lambda: participant_of(runtime, "alice"), "the merged audio never identified")

    # They take the association their audio found, every one of them.
    participants = {
        runtime.participants.resolve(segment=PerceptionSegmentRef(source, f"short-{index}"))
        for index in range(3)
    }
    assert participants == {participant_of(runtime, "alice")}
    await persona.on_stop()
    await runtime.aclose()


async def test_short_segments_lead_the_next_longer_one_into_its_vector(tmp_path: Path) -> None:
    inference = SensorInference()
    runtime = avatar_runtime(tmp_path, inference)
    persona = persona_for(runtime, "speaker")
    await persona.on_start()
    source = PerceptionSourceRef("device", 1)
    spoken = {"short-0": 0.8, "short-1": 0.7, "long": 1.2}
    for name, seconds in spoken.items():
        utter(runtime, source, name, "alice", heard=seconds + 0.2, spoken=seconds)
    await wait_until(lambda: len(inference.searches) == 1, "the long one was never searched")

    # Alone it is 1.2 s at its own length; led by the 1.5 s of short speech before it, it is
    # one vector of 2.7 s, and the short segments take its association.
    assert inference.vector_samples == [43200]
    alice = participant_of(runtime, "alice")
    heard = [
        runtime.participants.resolve(segment=PerceptionSegmentRef(source, name)) for name in spoken
    ]
    assert alice is not None and heard == [alice] * 3
    await persona.on_stop()
    await runtime.aclose()


async def test_a_segment_with_its_own_subject_drops_the_short_speech_before_it(
    tmp_path: Path,
) -> None:
    inference = SensorInference()
    runtime = avatar_runtime(tmp_path, inference)
    persona = persona_for(runtime, "speaker")
    await persona.on_start()
    speaker = next(processor for processor in persona._processors if processor.name == "speaker")
    source = PerceptionSourceRef("device", 1)
    utter(runtime, source, "short", "alice", heard=1.0, spoken=0.8)
    await wait_until(lambda: speaker._shorts, "the short segment was never kept")
    speak(runtime, source, "named", "alice")  # Its subject named on its frames
    await wait_until(lambda: inference.searches, "the named segment was never searched")

    # The short speech cannot cross it to lead a later segment: it goes, unattributed.
    assert inference.vector_samples == [48000] and not speaker._shorts
    assert runtime.participants.resolve(segment=PerceptionSegmentRef(source, "short")) is None
    await persona.on_stop()
    await runtime.aclose()


@pytest.mark.parametrize("ended_by", ["cancelled", "new-generation"])
async def test_a_retired_source_drops_its_short_segments(ended_by: str, tmp_path: Path) -> None:
    runtime = avatar_runtime(tmp_path, SensorInference())
    persona = persona_for(runtime, "speaker")
    await persona.on_start()
    speaker = next(processor for processor in persona._processors if processor.name == "speaker")
    source = PerceptionSourceRef("device", 1)
    utter(runtime, source, "short", "alice", heard=1.0, spoken=0.8)
    await wait_until(lambda: speaker._shorts, "the short segment was never kept")
    if ended_by == "cancelled":
        runtime.perception.publish_observation(
            EnvObservation(
                kind=ObservationKind.SPEECH_CANCELLED,
                time_range=RuntimeTimeRange.point(runtime.clock.now()),
                source=source,
                segment=PerceptionSegmentRef(source, "gone"),
                metadata={"reason_code": "source_ended"},
            )
        )
    else:
        speak(runtime, PerceptionSourceRef("device", 2), "next", "alice", end=False)
    await wait_until(lambda: not speaker._shorts, "the retired source kept its short segment")
    await persona.on_stop()
    await runtime.aclose()


async def test_a_voice_is_its_segments_mean_each_by_the_seconds_its_vector_is_from(
    tmp_path: Path,
) -> None:
    def unit(*values: float) -> np.ndarray:
        vector = np.zeros(192)
        vector[: len(values)] = values
        return vector / np.linalg.norm(vector)

    # A 1.2 s utterance opens the voice, a window at 0.6 to it joins; the next window is 0 to
    # the first and 0.56 to their mean by seconds (0.40 unweighted, 0.04 merged 0.95 / 0.05).
    first, second, third = unit(1), unit(0.6, 0.8), unit(0, 0.9, 0.19**0.5)
    inference = SensorInference()
    inference.voices.extend((first, second, third))
    inference.replies.extend(["none"] * 3)  # Nobody's: the voice stays the session's own
    runtime = avatar_runtime(tmp_path, inference)
    persona = persona_for(runtime, "speaker")
    await persona.on_start()
    source = PerceptionSourceRef("device", 1)
    for index, (heard, spoken) in enumerate(((1.5, 1.2), (3.0, 2.6), (3.0, 2.6))):
        utter(runtime, source, f"u{index}", "alice", heard=heard, spoken=spoken)
        await wait_until(
            lambda index=index: len(inference.searches) == index + 1,
            f"utterance {index} was never searched",
        )

    assert inference.vector_samples == [19200, 48000, 48000]
    (participant_id,) = {
        runtime.participants.resolve(
            segment=PerceptionSegmentRef(source, f"u{index}")
        ).participant_id
        for index in range(3)
    }  # One voice: the last utterance joined what the first two made of it.
    cache = persona.persona_cache[participant_id]
    expected = 1.2 * first + 3.0 * second + 3.0 * third
    np.testing.assert_allclose(cache.speaker_vector, expected / np.linalg.norm(expected), rtol=1e-6)
    await persona.on_stop()
    await runtime.aclose()


def test_the_speaker_vector_model_resolves_its_pinned_revision_and_checksum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alphaavatar.plugins.persona.processors.speaker import model_files

    seen = {}
    monkeypatch.setattr(model_files, "resolve_hf_file", lambda **kwargs: seen.update(kwargs))
    model_files.resolve_speaker_model_path(SpeakerVectorRunner.MODEL_TYPE, models_dir="/models")
    config = model_files.SPEAKER_MODEL_CONFIG[SpeakerVectorRunner.MODEL_TYPE]
    assert (seen["repo_id"], seen["revision"], seen["sha256"]) == (
        config.hf_model,
        config.revision,
        config.sha256,
    )
    assert len(config.revision) == 40 and len(config.sha256) == 64


def test_the_speaker_vector_runner_feeds_the_graph_its_own_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import onnx
    from onnx import TensorProto, helper

    from alphaavatar.agents.runtime.inference import RunnerLaunch
    from alphaavatar.plugins.persona.processors.speaker import vector_runner
    from alphaavatar.plugins.persona.processors.speaker.fbank import FBank

    graph = helper.make_graph(
        [helper.make_node("ReduceMax", ["x"], ["embedding"], axes=[1], keepdims=0)],
        "speaker",
        [helper.make_tensor_value_info("x", TensorProto.FLOAT, ["N", "T", 80])],
        [helper.make_tensor_value_info("embedding", TensorProto.FLOAT, ["N", 80])],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 7
    onnx.save(model, tmp_path / "model.onnx")
    monkeypatch.setattr(
        vector_runner, "resolve_speaker_model_path", lambda *_, **__: str(tmp_path / "model.onnx")
    )
    runner = SpeakerVectorRunner()
    runner.configure(RunnerLaunch(str(tmp_path / "avatar"), str(tmp_path / "models")))
    runner.initialize()

    waveform = (0.1 * np.random.default_rng(0).standard_normal(16000)).astype(np.float32)
    result = np.frombuffer(runner.run(waveform.tobytes()), dtype=np.float32)
    expected = FBank(80, sample_rate=16000, mean_nor=True)(waveform).max(axis=1).reshape(-1)
    np.testing.assert_allclose(result, expected, rtol=1e-6, atol=1e-6)


def traced(runtime: AvatarRuntime, stage: str) -> list[dict]:
    found = runtime.perception.input_trace.snapshot().to_dict()["records"]
    return [record for record in found if record["stage"] == stage]


async def test_a_segments_association_never_waits_on_the_identity_before_it(tmp_path: Path) -> None:
    # Identity and attributes have a lane of their own: while Alice's identity search holds,
    # Bob's window runs and the association a commit waits for is ready.
    inference = SensorInference()
    inference.hold_search = True
    runtime = avatar_runtime(tmp_path, inference)
    persona = persona_for(runtime, "speaker")
    await persona.on_start()
    source = PerceptionSourceRef("device", 1)
    speak(runtime, source, "a", "alice", explicit=False)
    async with asyncio.timeout(HANG_GUARD):
        await inference.search_held.wait()
    speak(runtime, source, "b", "bob", explicit=False)
    async with asyncio.timeout(2):  # Unbounded before: it waited for the search's release.
        while len(traced(runtime, "participant.segment_ready")) < 2:
            await asyncio.sleep(0.001)

    assert [r["outcome"] for r in traced(runtime, "participant.segment_ready")] == ["bound"] * 2
    assert inference.searches == ["speaker:alice"]  # Bob's waits behind it, on its lane.
    inference.search_release.set()
    await wait_until(lambda: participant_of(runtime, "bob") is not None, "Bob never identified")
    assert inference.searches == ["speaker:alice", "speaker:bob"]
    await persona.on_stop()
    await runtime.aclose()


def spoken_turn(runtime: AvatarRuntime, segment: str):
    """The Turn the engine would commit of one segment's speech."""
    (closed,) = (
        o
        for o in runtime.perception.speech.read_range(after_seq=0).items
        if o.kind == ObservationKind.SPEECH_SEGMENT and o.segment.segment_id == segment
    )
    return runtime.turn.commit_event_input(
        input_id=f"turn-{segment}",
        modality=TurnInputModality.AUDIO,
        text="Hello.",
        started_at=closed.time_range.start,
        committed_at=runtime.clock.now(),
        cutoff_sequence=runtime.perception.capture_cutoff().sequence,
        input_observation_ids=(closed.observation_id,),
    )


@pytest.mark.parametrize("found", [True, False], ids=["identified", "out-of-time"])
async def test_a_turns_context_waits_for_its_speakers_identity_within_its_bound(
    found: bool, tmp_path: Path
) -> None:
    # What the answer needs of its speech, its speaker's identity, before Context freezes;
    # bounded: a search out of time leaves the identity as it is, for later Turns. The
    # attributes that follow are not waited for.
    inference = SensorInference()
    inference.hold_search, inference.attribute_delay = True, 1.0
    runtime = avatar_runtime(tmp_path, inference)
    persona = persona_for(runtime, "speaker", identity_wait_sec=0.3)
    await persona.on_start()
    speak(runtime, PerceptionSourceRef("device", 1), "a", "alice", explicit=False)
    async with asyncio.timeout(HANG_GUARD):
        await inference.search_held.wait()
    snapshot = spoken_turn(runtime, "a")

    started = time.monotonic()
    waiting = asyncio.create_task(runtime.turn.wait_context_ready(snapshot))
    if found:
        await asyncio.sleep(0.05)
        inference.search_release.set()
    assert await asyncio.wait_for(waiting, 2) is True
    waited = time.monotonic() - started
    if found:
        assert waited < 0.3 and participant_of(runtime, "alice") is not None
    else:
        assert 0.3 <= waited < 0.6 and participant_of(runtime, "alice") is None
        inference.search_release.set()
        await wait_until(lambda: participant_of(runtime, "alice"), "the identity never settled")
    # A Turn of no speech waits for nothing.
    assert await asyncio.wait_for(runtime.turn.wait_context_ready(spoken_turn(runtime, "a")), 0.05)
    await persona.on_stop()
    await runtime.aclose()


async def test_a_full_identity_lane_retires_the_segment_waiting_longest_unsearched(
    tmp_path: Path,
) -> None:
    inference = SensorInference()
    inference.hold_search = True
    runtime = avatar_runtime(tmp_path, inference)
    persona = persona_for(runtime, "speaker", inference_queue_size=1)
    await persona.on_start()
    source = PerceptionSourceRef("device", 1)
    for segment, user in (("a", "alice"), ("b", "bob"), ("c", "alice")):
        speak(runtime, source, segment, user, explicit=False)
        count = "abc".index(segment) + 1
        await wait_until(
            lambda count=count: len(traced(runtime, "participant.segment_ready")) == count,
            f"segment {segment} was never associated",
        )
        if segment == "a":
            async with asyncio.timeout(HANG_GUARD):
                await inference.search_held.wait()
    inference.search_release.set()
    await wait_until(lambda: participant_of(runtime, "alice"), "Alice was never identified")
    for _ in range(10):
        await asyncio.sleep(0)
    # Bob's segment waited while Alice's searched, then gave way to the next, unsearched.
    assert "speaker:bob" not in inference.searches and participant_of(runtime, "bob") is None
    await persona.on_stop()
    await runtime.aclose()


async def test_a_cancelled_source_cancels_the_identity_its_segment_waits_on(tmp_path: Path) -> None:
    inference = SensorInference()
    inference.hold_search = True
    runtime = avatar_runtime(tmp_path, inference)
    persona = persona_for(runtime, "speaker", identity_wait_sec=HANG_GUARD)
    await persona.on_start()
    source = PerceptionSourceRef("device", 1)
    speak(runtime, source, "a", "alice", explicit=False)
    async with asyncio.timeout(HANG_GUARD):
        await inference.search_held.wait()
    waiting = asyncio.create_task(runtime.turn.wait_context_ready(spoken_turn(runtime, "a")))
    await asyncio.sleep(0.05)
    assert not waiting.done()  # It waits on the identity in flight.
    # The source is cancelled while it speaks again: its segment being identified goes too.
    speak(runtime, source, "b", "alice", end=False, explicit=False)
    runtime.perception.publish_observation(
        EnvObservation(
            kind=ObservationKind.SPEECH_CANCELLED,
            time_range=RuntimeTimeRange.point(runtime.clock.now()),
            source=source,
            segment=PerceptionSegmentRef(source, "b"),
            metadata={"reason_code": "source_ended"},
        )
    )
    await wait_until(lambda: traced(runtime, "speaker.identity"), "the search was never ended")
    # No identity will come: the Turn waiting for it goes on at once, not at its bound.
    assert await asyncio.wait_for(waiting, 1) is True
    inference.search_release.set()
    for _ in range(10):
        await asyncio.sleep(0)
    (identity,) = traced(runtime, "speaker.identity")
    assert identity["outcome"] == "cancelled" and participant_of(runtime, "alice") is None
    await persona.on_stop()
    await runtime.aclose()


def described(runtime: AvatarRuntime, persona, user: str):
    """The speaker attributes Persona holds for the user's participant, if any."""
    participant = participant_of(runtime, user)
    cache = persona.persona_cache.get(participant.participant_id) if participant else None
    return cache.profile_details if cache is not None else None


async def test_a_slow_attribute_never_holds_the_next_segments_association_or_identity(
    tmp_path: Path,
) -> None:
    # Attributes have their own lane: while Alice's are inferred, Bob's window, association
    # and identity complete, and his Turn's Context stops waiting as soon as he is known.
    inference = SensorInference()
    inference.hold_attribute = True
    runtime = avatar_runtime(tmp_path, inference)
    persona = persona_for(runtime, "speaker", identity_wait_sec=HANG_GUARD)
    await persona.on_start()
    source = PerceptionSourceRef("device", 1)
    speak(runtime, source, "a", "alice", explicit=False)
    async with asyncio.timeout(HANG_GUARD):
        await inference.attribute_held.wait()
    speak(runtime, source, "b", "bob", explicit=False)
    await wait_until(lambda: len(traced(runtime, "participant.segment_ready")) == 2, "unbound")
    ready = await asyncio.wait_for(runtime.turn.wait_context_ready(spoken_turn(runtime, "b")), 2)

    assert ready is True and participant_of(runtime, "bob") is not None
    assert described(runtime, persona, "alice") is None  # Still being inferred
    inference.attribute_release.set()
    await wait_until(lambda: described(runtime, persona, "bob"), "Bob was never described")
    assert inference.attributes == ["alice", "bob"] and described(runtime, persona, "alice")
    await persona.on_stop()
    await runtime.aclose()


async def test_a_full_attribute_lane_gives_way_without_holding_any_identity(tmp_path: Path) -> None:
    inference = SensorInference()
    inference.hold_attribute = True
    runtime = avatar_runtime(tmp_path, inference)
    persona = persona_for(runtime, "speaker", inference_queue_size=1)
    await persona.on_start()
    source = PerceptionSourceRef("device", 1)
    for segment, user in (("a", "alice"), ("b", "bob"), ("c", "carol")):
        speak(runtime, source, segment, user, explicit=False)
        await wait_until(lambda user=user: participant_of(runtime, user), f"{user} unknown")
        if segment == "a":
            async with asyncio.timeout(HANG_GUARD):
                await inference.attribute_held.wait()
    # Every identity settled while Alice's attributes held; Bob's waited, then gave way.
    inference.attribute_release.set()
    await wait_until(lambda: described(runtime, persona, "carol"), "Carol never described")
    assert inference.searches == ["speaker:alice", "speaker:bob", "speaker:carol"]
    assert inference.attributes == ["alice", "carol"] and described(runtime, persona, "bob") is None
    await persona.on_stop()
    await runtime.aclose()


@pytest.mark.parametrize("how", ["cancelled-source", "new-generation", "stop"])
async def test_an_attribute_of_a_retired_segment_is_reaped_and_writes_nothing(
    how: str, tmp_path: Path
) -> None:
    inference = SensorInference()
    inference.hold_attribute = True
    runtime = avatar_runtime(tmp_path, inference)
    persona = persona_for(runtime, "speaker")
    await persona.on_start()
    source = PerceptionSourceRef("device", 1)
    speak(runtime, source, "a", "alice", explicit=False)
    async with asyncio.timeout(HANG_GUARD):
        await inference.attribute_held.wait()
    alice = participant_of(runtime, "alice")
    cache = persona.cache_for(alice.participant_id)
    if how == "cancelled-source":
        speak(runtime, source, "b", "bob", end=False, explicit=False)
        runtime.perception.publish_observation(
            EnvObservation(
                kind=ObservationKind.SPEECH_CANCELLED,
                time_range=RuntimeTimeRange.point(runtime.clock.now()),
                source=source,
                segment=PerceptionSegmentRef(source, "b"),
                metadata={"reason_code": "source_ended"},
            )
        )
        await wait_until(lambda: traced(runtime, "speaker.attribute"), "it was never reaped")
    elif how == "new-generation":
        # The device reopened: its old generation's segments are retired as the new speaks.
        speak(runtime, PerceptionSourceRef("device", 2), "c", "bob", end=False, explicit=False)
        await wait_until(
            lambda: any(
                r["outcome"] == "released" for r in traced(runtime, "participant.segment_ready")
            )
            or not runtime.participants.source_is_current(source),
            "the old generation was never retired",
        )
    else:
        await asyncio.wait_for(persona.on_stop(), 2)  # Not held by the inference in flight
    inference.attribute_release.set()
    if how == "new-generation":
        await wait_until(lambda: traced(runtime, "speaker.attribute"), "it never ended")
    (attribute,) = traced(runtime, "speaker.attribute")
    expected = "done" if how == "new-generation" else "cancelled"  # Ran out, its segment gone
    assert attribute["outcome"] == expected and cache.profile_details is None
    if how != "stop":
        await persona.on_stop()
    await runtime.aclose()


async def test_a_late_attribute_never_describes_the_identity_that_replaced_its_own(
    tmp_path: Path,
) -> None:
    inference = SensorInference()
    inference.hold_attribute = True
    runtime = avatar_runtime(tmp_path, inference)
    persona = persona_for(runtime, "speaker")
    await persona.on_start()
    speak(runtime, PerceptionSourceRef("device", 1), "a", "alice", explicit=False)
    async with asyncio.timeout(HANG_GUARD):
        await inference.attribute_held.wait()
    alice = participant_of(runtime, "alice")
    corrected = runtime.participants.bind_user(
        IdentityRequest(
            participant_id=alice.participant_id,
            user_id="carol",
            source=IdentitySource.AGENT,
            expected_revision=alice.identity_revision,
            reason="The speaker said they are Carol",
        )
    )
    assert corrected == IdentityOutcome.APPLIED
    inference.attribute_release.set()
    await wait_until(lambda: traced(runtime, "speaker.attribute"), "it never ended")
    # Inferred for Alice's identity, it describes nobody now that the participant is Carol.
    assert persona.cache_for(alice.participant_id).profile_details is None
    await persona.on_stop()
    await runtime.aclose()


@pytest.mark.parametrize(
    ("sensor", "how"),
    [("speaker", "new-generation"), ("speaker", "cancelled-source"), ("face", "new-generation")],
)
async def test_late_sensor_result_from_a_retired_source_never_binds_identity(
    sensor: str, how: str, tmp_path: Path
) -> None:
    inference = SensorInference()
    inference.hold = "alice"
    runtime = avatar_runtime(tmp_path, inference)
    persona = persona_for(runtime, sensor)
    await persona.on_start()
    old, new = PerceptionSourceRef("device", 1), PerceptionSourceRef("device", 2)
    if sensor == "speaker":
        # A cancelled source must still have an open segment for the cancellation to apply.
        speak(runtime, old, "late", "alice", end=how != "cancelled-source")
    else:
        show(runtime, old, "alice")
    async with asyncio.timeout(HANG_GUARD):
        await inference.held.wait()

    if how == "cancelled-source":
        runtime.perception.publish_observation(
            EnvObservation(
                kind=ObservationKind.SPEECH_CANCELLED,
                time_range=RuntimeTimeRange.point(runtime.clock.now()),
                source=old,
                segment=PerceptionSegmentRef(old, "late"),
                metadata={"reason_code": "source_ended"},
            )
        )
    # The newer generation's evidence is a FIFO barrier behind the held late result.
    if sensor == "speaker":
        speak(runtime, new, "next", "bob")
    else:
        show(runtime, new, "bob")
    await wait_until(
        lambda: not runtime.participants.source_is_current(old), "The old source was not retired"
    )
    inference.release.set()
    await wait_until(lambda: participant_of(runtime, "bob") is not None, "Barrier never resolved")

    assert participant_of(runtime, "alice") is None
    assert inference.searches == [f"{sensor}:bob"]
    for cache in persona.persona_cache.values():
        vector = cache.speaker_vector if sensor == "speaker" else cache.face_vector
        assert vector is None or cache.participant.user_id == "bob"
    await persona.on_stop()
    await runtime.aclose()


def sense(
    runtime: AvatarRuntime, sensor: str, source: PerceptionSourceRef, user: str, *, take: int = 0
) -> PerceptionEntityRef:
    """One observation of a user on a source that stays current; returns its physical entity."""
    if sensor == "speaker":
        speak(runtime, source, f"utterance-{take}", user)
        return PerceptionEntityRef(f"voice-{user}")
    show(runtime, source, user, later=take)
    return PerceptionEntityRef(f"face-{user}")


def observed(persona, participant_id: str, sensor: str) -> tuple[np.ndarray | None, object]:
    cache = persona.persona_cache.get(participant_id)
    if cache is None:
        return None, None
    vector = cache.speaker_vector if sensor == "speaker" else cache.face_vector
    details = cache.profile_details
    return vector, details.gender if details is not None else None


def persona_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("alphaavatar.plugins.persona")
        and record.levelno >= logging.WARNING
    ]


@pytest.mark.parametrize("reply", ["matched", "none", "empty-user"])
@pytest.mark.parametrize("sensor", ["speaker", "face"])
async def test_vector_search_miss_keeps_evidence_with_the_participant_without_binding(
    sensor: str, reply: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="alphaavatar.plugins.persona")
    inference = SensorInference()
    inference.replies.append(reply)
    runtime = avatar_runtime(tmp_path, inference)
    persona = persona_for(runtime, sensor)
    await persona.on_start()
    source = PerceptionSourceRef("device", 1)
    entity = sense(runtime, sensor, source, "alice")
    await wait_until(
        lambda: runtime.participants.resolve(source=source, entity=entity) is not None,
        f"{sensor} entity was never associated",
    )
    participant = runtime.participants.resolve(source=source, entity=entity)
    await wait_until(
        lambda: observed(persona, participant.participant_id, sensor)[1] is not None,
        f"{sensor} evidence was not applied",
    )

    current = runtime.participants.get(participant.participant_id)
    generated = runtime.session.get_identity(participant.participant_id, 0)
    vector, gender = observed(persona, participant.participant_id, sensor)
    assert generated.user_id not in (None, "alice")
    if reply == "matched":
        # Control: the guards still let a valid same-source match bind the stored user.
        assert (current.user_id, current.identity_revision) == ("alice", 1)
    else:
        # A miss is no identity decision: the generated user and its version stay intact.
        assert current == generated
        assert participant_of(runtime, "alice") is None
    np.testing.assert_allclose(vector, embedding("alice", 192 if sensor == "speaker" else 512))
    assert gender is not None
    assert inference.searches == [f"{sensor}:alice"]
    assert runtime.participants.source_is_current(source)
    assert persona_warnings(caplog) == []
    await persona.on_stop()
    await runtime.aclose()


@pytest.mark.parametrize("reply", ["matched", "none"])
@pytest.mark.parametrize("sensor", ["speaker", "face"])
async def test_identity_switch_during_vector_search_discards_the_late_result(
    sensor: str, reply: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="alphaavatar.plugins.persona")
    inference = SensorInference()
    # The held answer, the barrier participant's match, then the follow-up's miss.
    inference.replies.extend((reply, "matched", "none"))
    inference.hold_search = True
    runtime = avatar_runtime(tmp_path, inference)
    persona = persona_for(runtime, sensor)
    await persona.on_start()
    source = PerceptionSourceRef("device", 1)
    entity = sense(runtime, sensor, source, "alice")
    async with asyncio.timeout(HANG_GUARD):
        await inference.search_held.wait()

    # The Agent corrects the speaker to someone never perceived while the lookup is in flight.
    before = runtime.participants.resolve(source=source, entity=entity)
    outcome = runtime.participants.bind_user(
        IdentityRequest(
            participant_id=before.participant_id,
            user_id="carol",
            source=IdentitySource.AGENT,
            expected_revision=before.identity_revision,
            reason="The speaker introduced themself as Carol.",
        )
    )
    assert outcome == IdentityOutcome.APPLIED
    inference.search_release.set()
    # Sensor work is serial: another person's resolution proves the late result was handled.
    sense(runtime, sensor, PerceptionSourceRef("barrier", 1), "bob")
    await wait_until(lambda: participant_of(runtime, "bob") is not None, "Barrier never resolved")

    carol = runtime.participants.get(before.participant_id)
    assert carol.user_id == "carol" and carol.identity_revision == before.identity_revision + 1
    assert participant_of(runtime, "alice") is None
    # Evidence judged against the previous identity never lands in Carol's observations.
    assert observed(persona, carol.participant_id, sensor) == (None, None)
    assert runtime.participants.source_is_current(source)
    assert runtime.participants.resolve(source=source, entity=entity) == carol

    # The same, still-current source keeps working for the corrected identity.
    sense(runtime, sensor, source, "alice", take=1)
    await wait_until(
        lambda: observed(persona, carol.participant_id, sensor)[1] is not None,
        "The corrected participant stopped receiving evidence",
    )
    vector, _ = observed(persona, carol.participant_id, sensor)
    np.testing.assert_allclose(vector, embedding("alice", 192 if sensor == "speaker" else 512))
    assert runtime.participants.get(carol.participant_id) == carol
    assert inference.searches == [f"{sensor}:alice", f"{sensor}:bob", f"{sensor}:alice"]
    assert persona_warnings(caplog) == []
    await persona.on_stop()
    await runtime.aclose()


def sensor_state(runtime: AvatarRuntime, persona, sensor: str) -> tuple:
    identities = sorted(
        (p.participant_id, p.user_id, p.identity_revision)
        for p in runtime.session.participants.values()
    )
    evidence = sorted(
        (pid, vector is not None and vector.tobytes(), str(gender))
        for pid in persona.persona_cache
        for vector, gender in [observed(persona, pid, sensor)]
    )
    return identities, evidence


@pytest.mark.parametrize("timing", ["pending", "ready-at-stop"])
@pytest.mark.parametrize("stage", ["model", "search"])
@pytest.mark.parametrize("sensor", ["speaker", "face"])
async def test_stop_with_pending_sensor_work_reaps_it_and_admits_no_late_result(
    sensor: str, stage: str, timing: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inference = SensorInference()
    if stage == "model":
        inference.hold = "alice"
        held, release = inference.held, inference.release
    else:
        inference.hold_search = True
        held, release = inference.search_held, inference.search_release
    runtime = avatar_runtime(tmp_path, inference)
    persona = persona_for(runtime, sensor)
    before = asyncio.all_tasks()
    await persona.on_start()
    sense(runtime, sensor, PerceptionSourceRef("device", 1), "alice")
    async with asyncio.timeout(HANG_GUARD):
        await held.wait()

    if timing == "ready-at-stop":
        # The awaited call completes exactly as the processor begins to stop.
        (processor,) = persona._processors  # Read-only lookup of the single enabled sensor.
        stop = processor._stop

        async def stop_with_ready_result(*, finalize: bool) -> None:
            release.set()
            await stop(finalize=finalize)

        monkeypatch.setattr(processor, "_stop", stop_with_ready_result)

    async with asyncio.timeout(HANG_GUARD):
        await persona.on_stop()
    # Reaped by stop itself, before any later runtime cleanup could hide a straggler.
    assert [task.get_name() for task in asyncio.all_tasks() - before if not task.done()] == []
    stopped = sensor_state(runtime, persona, sensor)
    release.set()
    for _ in range(10):
        await asyncio.sleep(0)
    assert sensor_state(runtime, persona, sensor) == stopped
    if timing == "pending":
        # A cancelled call chain delivers nothing: no identity decision and no evidence.
        assert participant_of(runtime, "alice") is None
        assert all(
            vector is None
            for vector, _ in (observed(persona, pid, sensor) for pid in persona.persona_cache)
        )
        assert "alice" not in inference.saves
        assert inference.searches == ([] if stage == "model" else [f"{sensor}:alice"])
    await runtime.aclose()
