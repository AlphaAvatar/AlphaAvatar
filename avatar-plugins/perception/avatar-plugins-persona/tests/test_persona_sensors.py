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
from collections.abc import Callable
from datetime import date
from pathlib import Path

import numpy as np
import pytest

import alphaavatar.plugins.persona  # noqa: F401  Registers the default Persona plugin.
from alphaavatar.agents.runtime import AvatarRuntime, StateRuntime
from alphaavatar.agents.runtime.modules.participants import ParticipantRuntime
from alphaavatar.agents.runtime.plugin import AvatarModule, AvatarModulePlugin
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
from alphaavatar.core.time import RuntimeTimeRange
from alphaavatar.core.turn import TurnRuntime
from alphaavatar.core.workspace import WorkspacePaths, prepare_session_path, prepare_workspace
from alphaavatar.plugins.persona.processors.face.analysis_runner import FaceAnalysisRunner
from alphaavatar.plugins.persona.processors.speaker.attribute_runner import SpeakerAttributeRunner
from alphaavatar.plugins.persona.processors.speaker.vector_runner import SpeakerVectorRunner

HANG_GUARD = 30
VDB = "alphaavatar.persona.vdb.lancedb"
USERS = ("alice", "bob")
# Constant PCM levels identify each physical speaker's audio inside the offline model double.
LEVELS = {8192: "alice", 16384: "bob"}


def embedding(user: str, size: int) -> np.ndarray:
    vector = np.zeros(size, dtype=np.float32)
    vector[USERS.index(user)] = 1.0
    return vector


class SensorInference:
    """Offline Face/Speaker models and Persona VDB; one model request can be held open."""

    def __init__(self) -> None:
        self.searches: list[str] = []
        self.hold: str | None = None
        self.held, self.release = asyncio.Event(), asyncio.Event()

    async def _maybe_hold(self, user: str) -> None:
        if user == self.hold:
            self.hold = None
            self.held.set()
            await self.release.wait()

    async def do_inference(self, method: str, data: bytes) -> bytes | None:
        if method == SpeakerVectorRunner.INFERENCE_METHOD:
            user = LEVELS[round(np.frombuffer(data, dtype=np.float32)[0] * 32768)]
            await self._maybe_hold(user)
            return embedding(user, 192).tobytes()
        if method == SpeakerAttributeRunner.INFERENCE_METHOD:
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
            return json.dumps({"user_id": user}).encode()
        if request["op"] == "load":
            return b'{"details_items":[],"speaker_vector":null,"face_vector":null}'
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


def persona_for(runtime: AvatarRuntime, sensor: str):
    other = "face" if sensor == "speaker" else "speaker"
    return AvatarModulePlugin.create(
        AvatarModule.PERSONA,
        "default",
        runtime=runtime,
        vdb_config={},
        init_config={
            "profiler": {"enabled": False},
            other: {"enabled": False},
            **({"speaker": {"inference_queue_size": 8}} if sensor == "speaker" else {}),
        },
    )


def speak(
    runtime: AvatarRuntime,
    source: PerceptionSourceRef,
    segment: str,
    user: str,
    *,
    end: bool = True,
) -> None:
    """Publish one entity's 3 s utterance: exactly one model window, then the segment end."""
    level = next(level for level, name in LEVELS.items() if name == user)
    pcm = np.full(16000, level, dtype="<i2").tobytes()
    common = {
        "source": source,
        "segment": PerceptionSegmentRef(source, segment),
        "device_id": source.source_id,
        "entity": PerceptionEntityRef(f"voice-{user}"),
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


def show(runtime: AvatarRuntime, source: PerceptionSourceRef, *users: str) -> None:
    payload = VideoFramePayload(frame_id=None, width=640, height=480)
    payload.put(PayloadFormat.IMAGE_JPEG_BYTES, "+".join(users).encode(), view=PayloadView.RAW)
    runtime.perception.publish_observation(
        EnvObservation(
            kind=ObservationKind.VIDEO_FRAME,
            time_range=RuntimeTimeRange.point(runtime.clock.now()),
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
