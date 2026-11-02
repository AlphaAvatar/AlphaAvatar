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
"""Raw audio → real Silero VAD stream → Audio Activity speech frames and segments, offline."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from alphaavatar.agents.configs.runtime_config import RuntimeConfig
from alphaavatar.agents.runtime import AvatarRuntime, StateRuntime
from alphaavatar.agents.runtime.inference import InferenceExecutor
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.env.enums import ObservationKind, SpeechCancellationReason
from alphaavatar.core.env.schemas import PerceptionSourceRef
from alphaavatar.core.media import AudioFrame, AudioFramePayload
from alphaavatar.core.media.enums import PayloadFormat, PayloadView
from alphaavatar.core.session import SessionRuntime
from alphaavatar.core.time import RuntimeTime, RuntimeTimeRange
from alphaavatar.core.workspace import WorkspacePaths
from alphaavatar.plugins.router.processors.audio_activity import AudioActivityProcessor
from alphaavatar.plugins.router.processors.audio_activity.config import AudioActivityConfig
from alphaavatar.plugins.voice.vad import SileroVAD, SileroVADRunner
from alphaavatar.plugins.voice.vad.model_files import SILERO_MODEL_CONFIG

HANG_GUARD = 10
RATE, FRAME, WINDOW = 16_000, 160, SILERO_MODEL_CONFIG.window_size_samples
FRAME_NS = FRAME * 1_000_000_000 // RATE
# 16 silent frames, 32 speech frames, then silence. Both boundaries fall on a VAD window edge,
# so the expected speech region is exact: samples [2560, 7680).
SILENCE, SPEECH, TAIL = 16, 32, 16
SPEECH_START, SPEECH_END = SILENCE * FRAME, (SILENCE + SPEECH) * FRAME
# A 0.1 s pre-roll routes from sample 960: frame 6 is the first frame ending after it.
FIRST_ROUTED, LAST_SPOKEN = 6, SILENCE + SPEECH - 1


async def wait_until(condition: Callable[[], object], failure: str) -> None:
    try:
        async with asyncio.timeout(HANG_GUARD):
            while not condition():
                await asyncio.sleep(0.001)
    except TimeoutError:
        pytest.fail(failure, pytrace=False)


class ScriptedSilero:
    """Offline Silero runner: loud windows are speech; a gate holds inference as a backlog."""

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.gate.set()
        self.windows = 0

    async def do_inference(self, method: str, data: bytes) -> bytes:
        assert method == SileroVADRunner.INFERENCE_METHOD
        await self.gate.wait()
        audio = np.frombuffer(data, dtype=np.float32, count=WINDOW)
        self.windows += 1
        loud = np.count_nonzero(np.abs(audio) >= 1000 / 32767) * 2 >= audio.size
        state = np.zeros(SILERO_MODEL_CONFIG.state_size, dtype=np.float32)
        return np.concatenate(([0.9 if loud else 0.0], state)).astype(np.float32).tobytes()


class Microphone:
    """One input generation with exact, contiguous frame times and distinguishable PCM."""

    def __init__(self, runtime: AvatarRuntime, generation: int = 1) -> None:
        self.runtime, self.source = runtime, PerceptionSourceRef("microphone", generation)
        self.origin = runtime.perception.clock.now()
        self.sent: list[EnvObservation] = []

    def time(self, index: int) -> RuntimeTime:
        offset = index * FRAME_NS
        return RuntimeTime(self.origin.unix_ns + offset, self.origin.monotonic_ns + offset)

    def push(self, *values: int) -> None:
        for value in values:
            index = len(self.sent)
            frame_id = f"{self.source.source_id}:{self.source.source_generation}:{index}"
            frame = AudioFrame(RATE, 1, FRAME, np.full(FRAME, value, dtype="<i2").tobytes())
            observation = EnvObservation.audio_frame(
                time_range=RuntimeTimeRange(self.time(index), self.time(index + 1)),
                source=self.source,
                frame_id=frame_id,
                payload=AudioFramePayload.create(frame=frame, frame_id=frame_id),
            )
            self.runtime.perception.publish_observation(observation)
            self.sent.append(observation)

    def silence(self, count: int) -> None:
        # Quiet but nonzero and distinct, so concatenated PCM proves frame order.
        self.push(*(len(self.sent) + offset + 1 for offset in range(count)))

    def speech(self, count: int) -> None:
        self.push(*(1000 + len(self.sent) + offset for offset in range(count)))

    def pcm(self, first: int, last: int) -> bytes:
        return b"".join(self.frame(index).data for index in range(first, last + 1))

    def frame(self, index: int) -> AudioFrame:
        payload = self.sent[index].payload
        return payload.get(PayloadFormat.AUDIO_FRAME, view=PayloadView.RAW)


class Pipeline:
    def __init__(self, root: Path) -> None:
        workspace, session = WorkspacePaths.from_root(root), SessionRuntime(session_id="session")
        self.runtime = AvatarRuntime.create(
            workspace=workspace,
            session=session,
            session_path=workspace.data.sessions.get(session.session_id, date(2026, 1, 1)),
            state=StateRuntime(),
            config=RuntimeConfig(),
            inference=InferenceExecutor("/unused/inference.sock"),
        )
        self.silero = ScriptedSilero()
        vad = SileroVAD(
            min_speech_duration=0.05,
            min_silence_duration=0.1,
            smoothing_alpha=0.0,
            inference_timeout_sec=HANG_GUARD,
            inference_executor=self.silero,
        )
        self.processor = AudioActivityProcessor(
            runtime=self.runtime,
            vad=vad,
            config=AudioActivityConfig(pre_roll_sec=0.1, max_buffer_sec=2.0),
        )

    def speech(self, kind: ObservationKind | None = None) -> list[EnvObservation]:
        items = self.runtime.perception.speech.read_range(after_seq=0).items
        return [item for item in items if kind is None or item.kind == kind]

    async def consumed(self) -> None:
        """Every published audio event has been pushed into its VAD stream."""
        events = self.runtime.perception.events
        await wait_until(
            lambda: events.get_consumer_cursor(AudioActivityProcessor.CONSUMER_ID)
            == events.latest_seq,
            "audio activity never consumed its input",
        )

    def routed(self, segment) -> list[str]:
        return [
            item.metadata["source_observation_id"]
            for item in self.speech(ObservationKind.SPEECH_FRAME)
            if item.segment == segment
        ]


@pytest.fixture
async def pipeline(tmp_path: Path):
    pipeline = Pipeline(tmp_path)
    await pipeline.processor.start()
    try:
        yield pipeline
    finally:
        pipeline.silero.gate.set()
        await pipeline.processor.stop()
        await pipeline.runtime.aclose()


def assert_segment(pipeline: Pipeline, microphone: Microphone) -> EnvObservation:
    (segment,) = pipeline.speech(ObservationKind.SPEECH_SEGMENT)
    ids = [item.observation_id for item in microphone.sent]
    spoken = ids[FIRST_ROUTED : LAST_SPOKEN + 1]
    routed = pipeline.routed(segment.segment)

    # Live routing is a contiguous source-order run from the pre-roll edge, never duplicated.
    assert routed == ids[FIRST_ROUTED : FIRST_ROUTED + len(routed)]
    frames = [
        item
        for item in pipeline.speech(ObservationKind.SPEECH_FRAME)
        if item.segment == segment.segment
    ]
    assert [item.metadata["route_index"] for item in frames] == list(range(1, len(frames) + 1))
    assert [item.metadata.get("speech_event") for item in frames[:2]] == ["start", None]
    assert [item.metadata["is_pre_roll"] for item in frames[: len(spoken)]] == [
        index < SILENCE for index in range(FIRST_ROUTED, LAST_SPOKEN + 1)
    ]

    # Tail-silence backtracking: the segment ends at the last speech window, not at VAD's
    # end decision, and drops the trailing silence that was already routed while speaking.
    assert segment.payload.source_observation_ids == tuple(spoken)
    assert segment.payload.get(PayloadFormat.AUDIO_PCM16_BYTES, view=PayloadView.RAW) == (
        microphone.pcm(FIRST_ROUTED, LAST_SPOKEN)
    )
    assert (segment.metadata["route_start_sample"], segment.metadata["frame_count"]) == (
        FIRST_ROUTED * FRAME,
        len(spoken),
    )
    assert (segment.metadata["speech_start_sample"], segment.metadata["speech_end_sample"]) == (
        SPEECH_START,
        SPEECH_END,
    )
    assert segment.time_range == RuntimeTimeRange(
        microphone.time(SILENCE), microphone.time(LAST_SPOKEN + 1)
    )
    return segment


async def test_tail_silence_is_backtracked_out_of_the_segment(pipeline: Pipeline) -> None:
    microphone = Microphone(pipeline.runtime)
    microphone.silence(SILENCE)
    microphone.speech(SPEECH)
    await wait_until(lambda: pipeline.speech(ObservationKind.SPEECH_FRAME), "speech never began")
    for _ in range(TAIL):
        microphone.silence(1)  # Live, while VAD still reports speaking.
        await pipeline.consumed()
    await wait_until(
        lambda: pipeline.speech(ObservationKind.SPEECH_SEGMENT), "VAD never ended the segment"
    )

    segment = assert_segment(pipeline, microphone)
    # Trailing silence before the end decision was routed live, but is not speech.
    assert len(pipeline.routed(segment.segment)) > len(segment.payload.source_observation_ids)


@pytest.mark.parametrize("live_after", [False, True], ids=["whole-backlog", "backlog-then-live"])
async def test_late_vad_start_replays_the_backlog_window_in_source_order(
    pipeline: Pipeline, live_after: bool
) -> None:
    microphone = Microphone(pipeline.runtime)
    pipeline.silero.gate.clear()  # VAD falls behind the transport.
    microphone.silence(SILENCE)
    microphone.speech(SPEECH // 2 if live_after else SPEECH)
    if not live_after:
        microphone.silence(TAIL)
    await pipeline.consumed()
    # Nothing was decided while inference was held, so nothing may have been routed yet.
    assert pipeline.speech() == []

    pipeline.silero.gate.set()
    await wait_until(
        lambda: pipeline.speech(ObservationKind.SPEECH_FRAME), "late VAD start never routed"
    )
    if live_after:
        # The whole backlog window is replayed at once; newer frames then arrive live.
        (start,) = {item.segment for item in pipeline.speech(ObservationKind.SPEECH_FRAME)}
        ids = [item.observation_id for item in microphone.sent]
        assert pipeline.routed(start) == ids[FIRST_ROUTED:]
        microphone.speech(SPEECH - SPEECH // 2)
        microphone.silence(TAIL)
    await wait_until(
        lambda: pipeline.speech(ObservationKind.SPEECH_SEGMENT), "VAD never ended the segment"
    )
    assert_segment(pipeline, microphone)


async def test_retired_generation_cancels_its_open_segment_and_drops_late_frames(
    pipeline: Pipeline,
) -> None:
    old = Microphone(pipeline.runtime)
    old.silence(SILENCE)
    old.speech(8)  # Two speech windows start the segment.
    await wait_until(lambda: pipeline.speech(ObservationKind.SPEECH_FRAME), "speech never began")
    (old_segment,) = {item.segment for item in pipeline.speech(ObservationKind.SPEECH_FRAME)}

    pipeline.silero.gate.clear()  # Old results are still pending when the generation changes.
    old.speech(SPEECH - 8)
    new = Microphone(pipeline.runtime, generation=2)
    new.silence(SILENCE)
    old.silence(TAIL)  # A late reader of the retired generation keeps delivering.
    new.speech(SPEECH)
    new.silence(TAIL)
    await pipeline.consumed()
    pipeline.silero.gate.set()
    await wait_until(
        lambda: pipeline.speech(ObservationKind.SPEECH_SEGMENT), "new generation never ended"
    )

    (cancelled,) = pipeline.speech(ObservationKind.SPEECH_CANCELLED)
    assert cancelled.segment == old_segment
    assert cancelled.metadata["reason_code"] == (
        SpeechCancellationReason.SOURCE_GENERATION_RETIRED.value
    )
    segment = assert_segment(pipeline, new)
    assert segment.segment.source.source_id == old_segment.source.source_id
    assert segment.segment.source.source_generation > old_segment.source.source_generation
    # The retired generation produced no segment, and its late frames were never routed.
    late = {item.observation_id for item in old.sent[SILENCE + SPEECH :]}
    routed = {item.metadata.get("source_observation_id") for item in pipeline.speech()}
    assert not late & routed
    assert all(
        item.segment != old_segment for item in pipeline.speech(ObservationKind.SPEECH_SEGMENT)
    )
