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
from collections.abc import AsyncIterator, Callable
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from alphaavatar.agents.avatar.voice import (
    STTBase,
    STTCapabilities,
    STTInputMode,
    STTStreamBase,
    TranscriptionEvent,
    TranscriptionEventType,
)
from alphaavatar.agents.configs.runtime_config import RuntimeConfig
from alphaavatar.agents.router.enums import TurnTakingAction, TurnTakingMode
from alphaavatar.agents.router.models import TurnTakingModelBase, TurnTakingModelCapabilities
from alphaavatar.agents.router.schemas import (
    TurnTakingAssessment,
    TurnTakingDecision,
    TurnTakingEvidence,
)
from alphaavatar.agents.runtime import AvatarRuntime, StateRuntime
from alphaavatar.agents.runtime.inference import InferenceExecutor
from alphaavatar.agents.workspace import WorkspacePaths
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.env.enums import AnnotationKind, ObservationKind, SpeechCancellationReason
from alphaavatar.core.env.schemas import PerceptionSourceRef
from alphaavatar.core.media import AudioFrame, AudioFramePayload
from alphaavatar.core.media.enums import PayloadFormat, PayloadView
from alphaavatar.core.perception.enums import MediaModality, MediaSourceKind, MediaSourceState
from alphaavatar.core.perception.schemas import MediaSourceStateEvent
from alphaavatar.core.session import SessionRuntime
from alphaavatar.core.time import RuntimeTime, RuntimeTimeRange
from alphaavatar.plugins.router.processors.audio_activity import AudioActivityProcessor
from alphaavatar.plugins.router.processors.audio_activity.config import AudioActivityConfig
from alphaavatar.plugins.router.processors.speech import SpeechTranscriptionProcessor
from alphaavatar.plugins.router.processors.turn_taking import processor as turn_taking
from alphaavatar.plugins.router.processors.turn_taking.config import TurnTakingConfig
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
        self.timeouts = 0  # Next inferences that time out, as an overloaded runner would.

    async def do_inference(self, method: str, data: bytes) -> bytes:
        assert method == SileroVADRunner.INFERENCE_METHOD
        await self.gate.wait()
        if self.timeouts:
            self.timeouts -= 1
            raise TimeoutError
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
    def __init__(
        self,
        root: Path,
        *,
        pre_roll_sec: float = 0.1,
        event_maxlen: int = 8192,
        event_batch_size: int = 64,
    ) -> None:
        workspace, session = WorkspacePaths.from_root(root), SessionRuntime(session_id="session")
        self.runtime = AvatarRuntime.create(
            workspace=workspace,
            session=session,
            session_path=workspace.data.sessions.get(session.session_id, date(2026, 1, 1)),
            state=StateRuntime(),
            config=RuntimeConfig(perception={"event_maxlen": event_maxlen}),
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
            config=AudioActivityConfig(
                pre_roll_sec=pre_roll_sec, max_buffer_sec=2.0, event_batch_size=event_batch_size
            ),
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
async def pipeline(request: pytest.FixtureRequest, tmp_path: Path):
    pipeline = Pipeline(tmp_path, **getattr(request, "param", {}))
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


@pytest.mark.parametrize(
    ("backlog", "evicted"),
    # The 2 s bound keeps the last 200 frames. 210 frames evict only pre-roll (frames 0–9);
    # 240 frames evict frames 0–39, so 24 of the 32 speech frames are gone before VAD starts.
    [(210, 10), (240, 40)],
    ids=["pre-roll-evicted", "speech-evicted"],
)
async def test_speech_evicted_by_the_backlog_bound_is_cancelled_and_recovered(
    pipeline: Pipeline, backlog: int, evicted: int
) -> None:
    microphone = Microphone(pipeline.runtime)
    pipeline.silero.gate.clear()
    microphone.silence(SILENCE)
    microphone.speech(SPEECH)
    microphone.silence(backlog - SILENCE - SPEECH)
    await pipeline.consumed()
    pipeline.silero.gate.set()
    ids = [item.observation_id for item in microphone.sent]

    if evicted <= SILENCE:
        # Only pre-roll is lost; the utterance itself is complete and published as usual.
        await wait_until(
            lambda: pipeline.speech(ObservationKind.SPEECH_SEGMENT), "VAD never ended the segment"
        )
        (segment,) = pipeline.speech(ObservationKind.SPEECH_SEGMENT)
        assert segment.payload.source_observation_ids == tuple(ids[evicted : SPEECH_END // FRAME])
        assert segment.metadata["speech_start_sample"] == SPEECH_START
        assert pipeline.speech(ObservationKind.SPEECH_CANCELLED) == []
        return

    await wait_until(
        lambda: pipeline.speech(ObservationKind.SPEECH_CANCELLED), "lost speech was not cancelled"
    )
    (cancelled,) = pipeline.speech(ObservationKind.SPEECH_CANCELLED)
    # The truncated remainder never becomes an utterance: no frame, no segment, explicit gap.
    assert cancelled.metadata["reason_code"] == SpeechCancellationReason.INPUT_GAP.value
    assert pipeline.speech(ObservationKind.SPEECH_FRAME) == []
    assert pipeline.speech(ObservationKind.SPEECH_SEGMENT) == []
    records = pipeline.runtime.perception.input_trace.snapshot().to_dict()["records"]
    (lost,) = [record for record in records if record["stage"] == "audio.speech_lost"]
    assert (lost["reason"], lost["missing_count"]) == (
        "vad_backlog_overflow",
        evicted * FRAME - SPEECH_START,
    )

    # The next utterance runs on a fresh, caught-up VAD stream of the same input.
    await pipeline.consumed()
    offset = len(microphone.sent)
    microphone.silence(SILENCE)
    microphone.speech(SPEECH)
    microphone.silence(TAIL)
    await wait_until(
        lambda: pipeline.speech(ObservationKind.SPEECH_SEGMENT), "recovered speech never ended"
    )
    (segment,) = pipeline.speech(ObservationKind.SPEECH_SEGMENT)
    spoken = [item.observation_id for item in microphone.sent[offset + FIRST_ROUTED :]]
    assert segment.payload.source_observation_ids == tuple(spoken[: LAST_SPOKEN - FIRST_ROUTED + 1])
    assert segment.metadata["speech_start_sample"] == SPEECH_START
    assert segment.segment.source.source_generation > cancelled.segment.source.source_generation


def skipped(pipeline: Pipeline) -> list[dict]:
    records = pipeline.runtime.perception.input_trace.snapshot().to_dict()["records"]
    return [record for record in records if record["stage"] == "audio.speech_skipped"]


@pytest.mark.parametrize(
    ("gap", "pause"),
    [("evicted", 0), ("evicted", 5), ("rejected", 0)],
    ids=["evicted-continuous", "evicted-short-pause", "vad-rejected-continuous"],
)
async def test_speech_continuing_through_a_gap_is_not_admitted_as_a_new_utterance(
    pipeline: Pipeline, gap: str, pause: int
) -> None:
    microphone = Microphone(pipeline.runtime)
    pipeline.silero.gate.clear()
    microphone.silence(SILENCE)
    # 2.4 s of backlog evicts the speech start; 2.84 s also overflows the 256-frame VAD queue.
    microphone.speech(224 if gap == "evicted" else 268)
    await pipeline.consumed()
    pipeline.silero.gate.set()
    if gap == "evicted":
        await wait_until(
            lambda: pipeline.speech(ObservationKind.SPEECH_CANCELLED), "lost speech not cancelled"
        )
    await pipeline.consumed()

    # The user keeps talking: the rebuilt stream opens inside the utterance cut by the gap.
    microphone.silence(pause)  # Shorter than the VAD's 0.1 s end-of-speech silence.
    microphone.speech(SPEECH)
    microphone.silence(TAIL)
    # Its end is a reliable boundary, so the next utterance is admitted normally.
    utterance = len(microphone.sent)
    microphone.silence(SILENCE)
    microphone.speech(SPEECH)
    microphone.silence(TAIL)
    await wait_until(
        lambda: pipeline.speech(ObservationKind.SPEECH_SEGMENT), "the next utterance never ended"
    )

    ids = [item.observation_id for item in microphone.sent]
    (segment,) = pipeline.speech(ObservationKind.SPEECH_SEGMENT)
    routed = {
        item.metadata["source_observation_id"]
        for item in pipeline.speech()
        if item.kind == ObservationKind.SPEECH_FRAME
    }
    # Nothing before the confirmed boundary was routed; the new utterance is complete.
    assert routed <= set(ids[utterance:])
    assert set(ids[utterance + SILENCE : utterance + SILENCE + SPEECH]) <= set(
        segment.payload.source_observation_ids
    )
    assert set(segment.payload.source_observation_ids) <= set(ids[utterance:])
    assert [record["reason"] for record in skipped(pipeline)] == ["unconfirmed_boundary"]
    assert segment.segment.source.source_generation > 1
    # A VAD queue rejection retires an idle stream; only evicted speech has a segment to cancel.
    assert len(pipeline.speech(ObservationKind.SPEECH_CANCELLED)) == (gap == "evicted")


async def evict_speech_start(pipeline: Pipeline, microphone: Microphone) -> None:
    """Lose the start of an utterance to the 2 s bound; its stream is cancelled and rebuilt."""
    pipeline.silero.gate.clear()
    microphone.silence(SILENCE)
    microphone.speech(224)
    await pipeline.consumed()
    pipeline.silero.gate.set()
    await wait_until(
        lambda: pipeline.speech(ObservationKind.SPEECH_CANCELLED), "lost speech not cancelled"
    )
    await pipeline.consumed()


def assert_only_utterance(
    pipeline: Pipeline, microphone: Microphone, utterance: int, speech: int
) -> None:
    ids = [item.observation_id for item in microphone.sent]
    (segment,) = pipeline.speech(ObservationKind.SPEECH_SEGMENT)
    routed = {
        item.metadata["source_observation_id"]
        for item in pipeline.speech(ObservationKind.SPEECH_FRAME)
    }
    assert routed <= set(ids[utterance:])
    assert set(segment.payload.source_observation_ids) <= set(ids[utterance:])
    # The new utterance itself is complete: every one of its speech frames is in the segment.
    assert set(ids[speech : speech + SPEECH]) <= set(segment.payload.source_observation_ids)


async def test_recovery_survives_a_stream_that_fails_before_its_boundary(
    pipeline: Pipeline,
) -> None:
    microphone = Microphone(pipeline.runtime)
    await evict_speech_start(pipeline, microphone)
    microphone.speech(16)  # The user keeps talking into the rebuilt stream.
    await wait_until(lambda: skipped(pipeline), "the continuation was never observed")
    await fail_vad(pipeline, microphone, speech=True)

    # The next stream still opens mid-utterance and must inherit the unconfirmed boundary.
    microphone.speech(SPEECH)
    microphone.silence(TAIL)
    utterance = len(microphone.sent)
    microphone.silence(SILENCE)
    microphone.speech(SPEECH)
    microphone.silence(TAIL)
    await wait_until(
        lambda: pipeline.speech(ObservationKind.SPEECH_SEGMENT), "the next utterance never ended"
    )
    assert_only_utterance(pipeline, microphone, utterance, utterance + SILENCE)
    assert len(skipped(pipeline)) == 2


@pytest.mark.parametrize("pipeline", [{"event_maxlen": 64}], indirect=True)
async def test_input_first_seen_after_a_perception_gap_must_confirm_a_boundary(
    pipeline: Pipeline,
) -> None:
    microphone = Microphone(pipeline.runtime)
    # 112 events reach a 64-event window before the consumer runs: it first meets this input
    # in the middle of its speech.
    microphone.silence(SILENCE)
    microphone.speech(96)
    await pipeline.consumed()
    records = pipeline.runtime.perception.input_trace.snapshot().to_dict()["records"]
    assert [record["stage"] for record in records].count("audio.input_gap") == 1

    microphone.silence(TAIL)
    utterance = len(microphone.sent)
    microphone.silence(SILENCE)
    microphone.speech(SPEECH)
    microphone.silence(TAIL)
    await wait_until(
        lambda: pipeline.speech(ObservationKind.SPEECH_SEGMENT), "the next utterance never ended"
    )
    assert_only_utterance(pipeline, microphone, utterance, utterance + SILENCE)
    assert [record["reason"] for record in skipped(pipeline)] == ["unconfirmed_boundary"]


@pytest.mark.parametrize("pipeline", [{"pre_roll_sec": 0.3}], indirect=True)
async def test_pre_roll_after_a_gap_never_reaches_back_into_skipped_speech(
    pipeline: Pipeline,
) -> None:
    microphone = Microphone(pipeline.runtime)
    await evict_speech_start(pipeline, microphone)
    microphone.speech(SPEECH)
    # 0.16 s of silence confirms the boundary but is shorter than the 0.3 s pre-roll.
    safe = len(microphone.sent)
    microphone.silence(TAIL)
    microphone.speech(SPEECH)
    microphone.silence(TAIL)
    await wait_until(
        lambda: pipeline.speech(ObservationKind.SPEECH_SEGMENT), "the next utterance never ended"
    )
    # Pre-roll may cover the confirming silence, never the skipped speech before it.
    assert_only_utterance(pipeline, microphone, safe, safe + TAIL)


class FinalizingSTTStream(STTStreamBase):
    """Offline segment STT: every committed segment finalizes to the same words."""

    def __init__(self, source_id: str) -> None:
        self.source_id, self.segments = source_id, []
        self._events: asyncio.Queue[TranscriptionEvent | None] = asyncio.Queue()

    def push_frame(self, frame: AudioFrame, *, segment_id: str) -> bool:
        if segment_id not in self.segments:
            self.segments.append(segment_id)
        return True

    def commit_segment(self, segment_id: str) -> bool:
        final = TranscriptionEventType.FINAL_TRANSCRIPT
        self._events.put_nowait(TranscriptionEvent(final, self.source_id, segment_id, "words"))
        return True

    def flush(self) -> bool:
        return True

    def end_input(self) -> bool:
        self._events.put_nowait(None)
        return True

    async def _iterate(self) -> AsyncIterator[TranscriptionEvent]:
        while (event := await self._events.get()) is not None:
            yield event

    def __aiter__(self) -> AsyncIterator[TranscriptionEvent]:
        return self._iterate()

    async def aclose(self) -> None:
        self._events.put_nowait(None)


class FinalizingSTT(STTBase):
    def __init__(self) -> None:
        self.streams: list[FinalizingSTTStream] = []

    @property
    def provider(self) -> str:
        return "offline"

    @property
    def model(self) -> str:
        return "offline"

    @property
    def capabilities(self) -> STTCapabilities:
        return STTCapabilities(STTInputMode.SEGMENT, False, False)

    def stream(self, *, source_id: str) -> FinalizingSTTStream:
        self.streams.append(FinalizingSTTStream(source_id))
        return self.streams[-1]


class EndpointModel(TurnTakingModelBase):
    """Offline endpoint detector: every complete, transcribed input ends its turn."""

    @property
    def name(self) -> str:
        return "offline_endpoint"

    @property
    def capabilities(self) -> TurnTakingModelCapabilities:
        return TurnTakingModelCapabilities(
            modes=frozenset({TurnTakingMode.AUDIO_ONLY}), uses_transcript=True
        )

    async def assess(self, evidence: TurnTakingEvidence) -> TurnTakingAssessment:
        return TurnTakingAssessment(
            input_id=evidence.input_id,
            revision=evidence.revision,
            turn_mode=evidence.turn_mode,
            confidence=1.0,
            end_of_turn_probability=1.0,
        )


def commits(runtime: AvatarRuntime) -> list[TurnTakingDecision]:
    events = runtime.perception.annotation_events.read_range(after_seq=0).items
    decisions = (
        TurnTakingDecision.from_annotation(event.annotation)
        for event in events
        if event.annotation.kind == AnnotationKind.INTERACTION_TURN
    )
    return [decision for decision in decisions if decision.action == TurnTakingAction.COMMIT]


@pytest.mark.parametrize("pipeline", [{"event_maxlen": 64}], indirect=True)
@pytest.mark.parametrize("racing", [False, True], ids=["snapshot-at-gap", "state-after-gap"])
async def test_snapshot_newer_than_a_gap_keeps_the_boundary_requirement(
    pipeline: Pipeline, racing: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = pipeline.runtime
    monkeypatch.setattr(
        turn_taking, "create_turn_taking_model", lambda name, inference_executor: EndpointModel()
    )
    stt = FinalizingSTT()
    listeners = (
        SpeechTranscriptionProcessor(runtime=runtime, stt=stt, close_timeout_sec=1),
        turn_taking.TurnTakingProcessor(
            runtime=runtime, config=TurnTakingConfig(transcript_wait_sec=HANG_GUARD)
        ),
    )
    for listener in listeners:
        await listener.start()
    try:
        microphone = Microphone(runtime)

        def publish(state: MediaSourceState):
            event = MediaSourceStateEvent(
                microphone.source, MediaModality.AUDIO, MediaSourceKind.MICROPHONE, state
            )
            return runtime.perception.publish_source_state(event)

        snapshot, raced = runtime.perception.get_source_states, []

        def racing_snapshot(**filters):
            # A producer thread mutes and unmutes this generation after the gap batch was read.
            if racing and filters.get("modality") == MediaModality.AUDIO and not raced:
                raced.extend(
                    publish(state) for state in (MediaSourceState.MUTED, MediaSourceState.ACTIVE)
                )
            return snapshot(**filters)

        monkeypatch.setattr(runtime.perception, "get_source_states", racing_snapshot)
        publish(MediaSourceState.ACTIVE)
        microphone.silence(SILENCE)
        microphone.speech(80)  # 97 events reach a 64-event window before the consumer runs.
        await pipeline.consumed()
        assert [event.sequence for event in raced] == ([98, 99] if racing else [])

        # Later audio arrives within the window, so this stays the only gap.
        microphone.speech(SPEECH)  # The same sentence continues.
        microphone.silence(TAIL)
        await pipeline.consumed()
        utterance = len(microphone.sent)
        microphone.silence(SILENCE)
        microphone.speech(SPEECH)
        await pipeline.consumed()
        microphone.silence(TAIL)
        await wait_until(lambda: commits(runtime), "the next utterance never committed")
        records = runtime.perception.input_trace.snapshot().to_dict()["records"]
        assert [record["stage"] for record in records].count("audio.input_gap") == 1

        # The tail never reached STT or Turn-taking; only the new utterance committed.
        assert_only_utterance(pipeline, microphone, utterance, utterance + SILENCE)
        (segment,) = pipeline.speech(ObservationKind.SPEECH_SEGMENT)
        assert [item for stream in stt.streams for item in stream.segments] == [
            segment.segment.segment_id
        ]
        assert len(commits(runtime)) == 1
    finally:
        for listener in reversed(listeners):
            await listener.stop()


class ConsumerGate:
    """Scheduling barrier: Audio Activity reads only as many event batches as the test allows."""

    def __init__(self, pipeline: Pipeline, monkeypatch: pytest.MonkeyPatch) -> None:
        events = pipeline.runtime.perception.events
        self.allowed: int | None = None
        self.parked, self._changed = False, asyncio.Event()
        original = events.wait_for_pending

        async def wait_for_pending(*, consumer_id: str, **options: object) -> bool:
            if consumer_id == AudioActivityProcessor.CONSUMER_ID:
                while self.allowed == 0:
                    self.parked = True
                    self._changed.clear()
                    await self._changed.wait()
                self.parked = False
                if self.allowed is not None:
                    self.allowed -= 1
            return await original(consumer_id=consumer_id, **options)

        monkeypatch.setattr(events, "wait_for_pending", wait_for_pending)

    def allow(self, batches: int | None) -> None:
        self.allowed = batches
        self._changed.set()


def stages(pipeline: Pipeline, stage: str) -> int:
    records = pipeline.runtime.perception.input_trace.snapshot().to_dict()["records"]
    return [record["stage"] for record in records].count(stage)


async def fail_vad(pipeline: Pipeline, microphone: Microphone, *, speech: bool = False) -> None:
    """Retire the current stream for a reason that is not a continuity gap."""
    # Read-only: the stream object, so its failure can be awaited before more audio arrives.
    stream = pipeline.processor._sources[microphone.source]
    # Queue the frames behind the inference gate before the timeout: a stream that has
    # already failed would rightly reject them as an input gap (VAD_INPUT_REJECTED).
    pipeline.silero.gate.clear()
    microphone.speech(4) if speech else microphone.silence(4)
    await pipeline.consumed()
    pipeline.silero.timeouts = 1
    pipeline.silero.gate.set()
    await wait_until(lambda: stream.failed, "the stream never failed")
    await pipeline.consumed()


@pytest.mark.parametrize("pipeline", [{"event_maxlen": 64, "event_batch_size": 8}], indirect=True)
async def test_confirmed_boundary_is_not_reimposed_by_the_rest_of_its_gap_window(
    pipeline: Pipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate, microphone = ConsumerGate(pipeline, monkeypatch), Microphone(pipeline.runtime)
    gate.allow(0)
    microphone.silence(40)
    microphone.speech(40)  # 80 events outrun the parked consumer: it keeps the last 64.
    # Two batches carry 16 frames of silence, enough for the rebuilt stream's boundary.
    gate.allow(2)
    await wait_until(
        lambda: gate.parked and microphone.source.source_id not in pipeline.processor._recovering,
        "the boundary was never confirmed inside the gap window",
    )
    gate.allow(None)  # The remaining pre-horizon events are consumed after the confirmation.
    await pipeline.consumed()

    # A later rebuild must not inherit a requirement this gap already released.
    await fail_vad(pipeline, microphone)
    first = len(microphone.sent)
    microphone.speech(SPEECH)  # No leading silence: only an unrecovering stream admits it.
    microphone.silence(TAIL)
    await wait_until(
        lambda: pipeline.speech(ObservationKind.SPEECH_SEGMENT), "the new speech never ended"
    )
    (segment,) = pipeline.speech(ObservationKind.SPEECH_SEGMENT)
    spoken = {item.observation_id for item in microphone.sent[first : first + SPEECH]}
    assert spoken <= set(segment.payload.source_observation_ids)
    assert (stages(pipeline, "audio.input_gap"), skipped(pipeline)) == (1, [])


@pytest.mark.parametrize("pipeline", [{"event_maxlen": 64}], indirect=True)
async def test_each_gap_requires_its_own_boundary(
    pipeline: Pipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate, microphone = ConsumerGate(pipeline, monkeypatch), Microphone(pipeline.runtime)
    for gap in (1, 2):
        if gap == 2:
            # No stream is active when the second gap arrives; only its own evidence counts.
            await fail_vad(pipeline, microphone)
        gate.allow(0)
        microphone.speech(80)  # Continuous speech outruns the consumer: a gap mid-utterance.
        gate.allow(None)
        await pipeline.consumed()
        microphone.speech(SPEECH)  # The cut utterance continues, then ends.
        microphone.silence(TAIL)
        await pipeline.consumed()
        assert (stages(pipeline, "audio.input_gap"), len(skipped(pipeline))) == (gap, gap)

    utterance = len(microphone.sent)
    microphone.silence(SILENCE)
    microphone.speech(SPEECH)
    microphone.silence(TAIL)
    await wait_until(
        lambda: pipeline.speech(ObservationKind.SPEECH_SEGMENT), "the next utterance never ended"
    )
    assert_only_utterance(pipeline, microphone, utterance, utterance + SILENCE)


@pytest.mark.parametrize("pipeline", [{"event_maxlen": 64}], indirect=True)
async def test_generation_first_seen_after_the_horizon_is_admitted_at_once(
    pipeline: Pipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate, old = ConsumerGate(pipeline, monkeypatch), Microphone(pipeline.runtime)
    gate.allow(0)
    old.speech(80)
    gate.allow(None)
    await pipeline.consumed()

    # A reconnect after the gap was read: its audio was never cut, so no boundary is owed.
    new = Microphone(pipeline.runtime, generation=2)
    new.speech(SPEECH)
    new.silence(TAIL)
    await wait_until(
        lambda: pipeline.speech(ObservationKind.SPEECH_SEGMENT), "the new generation never ended"
    )
    (segment,) = pipeline.speech(ObservationKind.SPEECH_SEGMENT)
    spoken = {item.observation_id for item in new.sent[:SPEECH]}
    assert spoken <= set(segment.payload.source_observation_ids)
    assert segment.payload.source_observation_ids[0] == new.sent[0].observation_id
    assert stages(pipeline, "audio.input_gap") == 1
