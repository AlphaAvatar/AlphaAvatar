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
from alphaavatar.core.media import AudioFrame, AudioFramePayload, VideoFramePayload
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
from alphaavatar.plugins.persona.processors.speaker.vector_runner import SpeakerVectorRunner

HANG_GUARD = 30
VDB = "alphaavatar.persona.vdb.lancedb"
USERS = ("alice", "bob")
# Constant PCM levels identify each physical speaker's audio inside the offline model double.
LEVELS = {8192: "alice", 16384: "bob"}
# The Persona VDB runner answers a miss with no result, or with a row that has no user.
SEARCH_REPLIES = {"none": None, "empty-user": {"user_id": "", "score": 0.99}}


def embedding(user: str, size: int) -> np.ndarray:
    vector = np.zeros(size, dtype=np.float32)
    vector[USERS.index(user)] = 1.0
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
        self.saves: list[str] = []

    async def _maybe_hold(self, user: str) -> None:
        if user == self.hold:
            self.hold = None
            self.held.set()
            await self.release.wait()

    async def do_inference(self, method: str, data: bytes) -> bytes | None:
        if method == SpeakerVectorRunner.INFERENCE_METHOD:
            user = LEVELS[round(np.frombuffer(data, dtype=np.float32)[0] * 32768)]
            if user == self.fail:
                raise RuntimeError("speaker vector runner failed")
            await self._maybe_hold(user)
            return embedding(user, 192).tobytes()
        if method == SpeakerAttributeRunner.INFERENCE_METHOD:
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
            user = USERS[int(np.argmax(request["param"][f"{kind}_vector"]))]
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
        assert (current.user_id, current.identity_sequence) == ("alice", 1)
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
            basis_sequence=before.identity_sequence,
            reason="The speaker introduced themself as Carol.",
        )
    )
    assert outcome == IdentityOutcome.APPLIED
    inference.search_release.set()
    # Sensor work is serial: another person's resolution proves the late result was handled.
    sense(runtime, sensor, PerceptionSourceRef("barrier", 1), "bob")
    await wait_until(lambda: participant_of(runtime, "bob") is not None, "Barrier never resolved")

    carol = runtime.participants.get(before.participant_id)
    assert carol.user_id == "carol" and carol.identity_sequence == before.identity_sequence + 1
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
        (p.participant_id, p.user_id, p.identity_sequence)
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
