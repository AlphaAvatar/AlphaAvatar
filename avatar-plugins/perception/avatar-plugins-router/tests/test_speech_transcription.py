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
"""Speech → STT → Turn-taking → Turn cutoff correlation and stale-input rejection, offline."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

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
from alphaavatar.core.env.schemas import PerceptionSegmentRef, PerceptionSourceRef
from alphaavatar.core.media import AudioFrame, AudioFramePayload
from alphaavatar.core.session import SessionRuntime
from alphaavatar.core.turn.enums import TurnInputModality
from alphaavatar.plugins.router.processors.speech import SpeechTranscriptionProcessor
from alphaavatar.plugins.router.processors.turn_taking import processor as turn_taking
from alphaavatar.plugins.router.processors.turn_taking.config import TurnTakingConfig

HANG_GUARD = 10
WAIT, DEADLINE = 0.75, 3.0  # Turn taking's transcript wait and hard deadline, by default
MICROPHONE = {"source_id": "microphone", "source_generation": 1}


def avatar_runtime(root: Path) -> AvatarRuntime:
    workspace, session = WorkspacePaths.from_root(root), SessionRuntime(session_id="session")
    return AvatarRuntime.create(
        workspace=workspace,
        session=session,
        session_path=workspace.data.sessions.get(session.session_id, date(2026, 1, 1)),
        state=StateRuntime(),
        config=RuntimeConfig(),
        inference=InferenceExecutor("/unused/inference.sock"),
    )


async def wait_until(condition: Callable[[], object], failure: str) -> None:
    try:
        async with asyncio.timeout(HANG_GUARD):
            while not condition():
                await asyncio.sleep(0.001)
    except TimeoutError:
        pytest.fail(failure, pytrace=False)


class OfflineSTTStream(STTStreamBase):
    def __init__(self, source_id: str) -> None:
        self.source_id, self.closed = source_id, False
        self.frames: dict[str, int] = {}
        self.committed: list[str] = []
        self._events: asyncio.Queue[TranscriptionEvent | None] = asyncio.Queue()

    def push_frame(self, frame: AudioFrame, *, segment_id: str) -> bool:
        self.frames[segment_id] = self.frames.get(segment_id, 0) + 1
        return True

    def commit_segment(self, segment_id: str) -> bool:
        self.committed.append(segment_id)
        return True

    def flush(self) -> bool:
        return True

    def end_input(self) -> bool:
        self._events.put_nowait(None)
        return True

    def emit(self, kind: TranscriptionEventType, segment_id: str, text: str = "", **extra) -> None:
        self._events.put_nowait(TranscriptionEvent(kind, self.source_id, segment_id, text, **extra))

    async def _iterate(self) -> AsyncIterator[TranscriptionEvent]:
        while (event := await self._events.get()) is not None:
            yield event

    def __aiter__(self) -> AsyncIterator[TranscriptionEvent]:
        return self._iterate()

    async def aclose(self) -> None:
        self.closed = True
        self._events.put_nowait(None)


class OfflineSTT(STTBase):
    def __init__(self) -> None:
        self.streams: list[OfflineSTTStream] = []

    @property
    def provider(self) -> str:
        return "offline"

    @property
    def model(self) -> str:
        return "offline"

    @property
    def capabilities(self) -> STTCapabilities:
        return STTCapabilities(STTInputMode.SEGMENT, False, False)

    def stream(self, *, source_id: str) -> OfflineSTTStream:
        self.streams.append(OfflineSTTStream(source_id))
        return self.streams[-1]


class EndpointModel(TurnTakingModelBase):
    """Offline endpoint detector: every complete, transcribed input ends its turn, with
    ``end`` as its probability; or it ``fails``, or assesses without the ``transcript``. Asked
    what it can do, it holds the loop ``lag`` seconds: an assessment that starts late."""

    def __init__(
        self, end: float = 1.0, *, fails: bool = False, transcript: bool = True, lag: float = 0.0
    ) -> None:
        self.end, self.fails, self.transcript, self.lag = end, fails, transcript, lag

    @property
    def name(self) -> str:
        return "offline_endpoint"

    @property
    def capabilities(self) -> TurnTakingModelCapabilities:
        time.sleep(self.lag)
        return TurnTakingModelCapabilities(
            modes=frozenset({TurnTakingMode.AUDIO_ONLY}), uses_transcript=self.transcript
        )

    async def assess(self, evidence: TurnTakingEvidence) -> TurnTakingAssessment:
        if self.fails:
            raise RuntimeError("the endpoint model failed")
        return TurnTakingAssessment(
            input_id=evidence.input_id,
            revision=evidence.revision,
            turn_mode=evidence.turn_mode,
            confidence=1.0,
            end_of_turn_probability=self.end,
        )


@dataclass
class Listening:
    runtime: AvatarRuntime
    stt: OfflineSTT

    def speech(self, generation: int = 1) -> PerceptionSourceRef:
        return PerceptionSourceRef("router:speech:microphone", generation)

    def frame(self, source: PerceptionSourceRef, segment_id: str, index: int) -> None:
        payload = AudioFramePayload.create(
            frame=AudioFrame(16_000, 1, 160, bytes(320)), frame_id=None
        )
        metadata = {"route_index": index, "input_source": MICROPHONE}
        if index == 1:
            metadata["speech_event"] = "start"
        self.runtime.perception.publish_observation(
            EnvObservation.speech_frame(
                time_range=self.runtime.clock.point(),
                source=source,
                segment=PerceptionSegmentRef(source, segment_id),
                payload=payload,
                metadata=metadata,
            )
        )

    def close(self, source: PerceptionSourceRef, segment_id: str) -> None:
        self.runtime.perception.publish_observation(
            EnvObservation.speech_segment(
                time_range=self.runtime.clock.point(),
                source=source,
                segment=PerceptionSegmentRef(source, segment_id),
                metadata={"speech_event": "end", "input_source": MICROPHONE},
            )
        )

    def utter(self, source: PerceptionSourceRef, segment_id: str, frames: int = 3) -> None:
        for index in range(1, frames + 1):
            self.frame(source, segment_id, index)
        self.close(source, segment_id)

    def records(self, *stages: str) -> list[dict]:
        records = self.runtime.perception.input_trace.snapshot().to_dict()["records"]
        return [record for record in records if not stages or record["stage"] in stages]

    def transcripts(self) -> list[EnvObservation]:
        items = self.runtime.perception.text.read_range(after_seq=0).items
        return [item for item in items if item.kind == ObservationKind.TRANSCRIPT_SEGMENT]

    def decisions(self) -> list[tuple[object, TurnTakingDecision]]:
        events = self.runtime.perception.annotation_events.read_range(after_seq=0).items
        return [
            (event, TurnTakingDecision.from_annotation(event.annotation))
            for event in events
            if event.annotation.kind == AnnotationKind.INTERACTION_TURN
        ]


@pytest.fixture
async def listening(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Listening]:
    """The chain; ``request.param`` may name its endpoint ``model`` (every complete input
    ends its turn), turn taking's ``settings`` and the ``addressing`` it requires."""
    param = getattr(request, "param", {})
    model = param.get("model", EndpointModel())
    monkeypatch.setattr(
        turn_taking, "create_turn_taking_model", lambda name, inference_executor: model
    )
    runtime, stt = avatar_runtime(tmp_path / "workspace"), OfflineSTT()
    transcription = SpeechTranscriptionProcessor(runtime=runtime, stt=stt, close_timeout_sec=1)
    # A generous transcript budget unless a test exercises its expiry deliberately.
    settings = {"transcript_wait_sec": HANG_GUARD}
    turns = turn_taking.TurnTakingProcessor(
        runtime=runtime,
        config=TurnTakingConfig(**settings | param.get("settings", {})),
        required_addressing_sources=param.get("addressing", ()),
    )
    for component in (transcription, turns):
        await component.start()
    yield Listening(runtime, stt)
    for component in (turns, transcription):
        await component.stop()
    await runtime.aclose()


async def test_stt_final_joins_segment_input_decision_and_turn_cutoff_evidence(
    listening: Listening,
) -> None:
    runtime, source = listening.runtime, listening.speech()
    listening.utter(source, "segment-a")
    await wait_until(
        lambda: listening.stt.streams and listening.stt.streams[0].committed, "no commit"
    )
    (stream,) = listening.stt.streams
    assert stream.frames == {"segment-a": 3} and stream.committed == ["segment-a"]
    stream.emit(TranscriptionEventType.FINAL_TRANSCRIPT, "segment-a", "private words")

    await wait_until(
        lambda: any(d.action == TurnTakingAction.COMMIT for _, d in listening.decisions()),
        "the transcribed input never committed",
    )
    (transcript,) = listening.transcripts()
    event, decision = next(item for item in listening.decisions() if item[1].action == "commit")
    assert transcript.observation_id in decision.input_observation_ids
    # Engine's admission step: freeze the Turn at the decision's own perception cutoff.
    snapshot = runtime.turn.commit_event_input(
        input_id=decision.input_id,
        modality=TurnInputModality.AUDIO,
        text="private words",
        started_at=transcript.time_range.start,
        committed_at=event.time_range.end,
        cutoff_sequence=event.sequence,
        input_observation_ids=decision.input_observation_ids,
        metadata={
            "revision": decision.revision,
            "decision_event_id": event.event_id,
            "decision_event_sequence": event.sequence,
            "decision_annotation_id": event.annotation.annotation_id,
        },
    )
    assert snapshot.cutoff.sequence == event.sequence
    assert transcript.observation_id in {
        item.payload.observation_id for item in snapshot.perception_events if item.observation
    }

    records = listening.records()
    by_stage = {record["stage"]: record for record in records}
    segment = by_stage["speech.close"]["segment_id"]
    final = by_stage["perception.transcript_final"]
    terminal = next(r for r in records if r["stage"] == "stt.terminal")
    assert by_stage["stt.commit"]["segment_id"] == segment == terminal["segment_id"]
    assert (terminal["outcome"], terminal["observation_id"], terminal["sequence"]) == (
        "final_text",
        final["observation_id"],
        final["sequence"],
    )
    accepted = next(r for r in records if r.get("state") == "final")
    assert (
        accepted["segment_id"] == segment and accepted["observation_id"] == final["observation_id"]
    )
    committed = next(
        r for r in records if r["stage"] == "input.decision" and r["action"] == "commit"
    )
    turn = by_stage["turn.committed"]
    assert committed["input_id"] == accepted["input_id"] == turn["input_id"]
    assert (turn["decision_id"], turn["sequence"]) == (
        committed["decision_id"],
        committed["sequence"],
    )
    assert turn["cutoff_sequence"] == committed["sequence"] > final["sequence"]
    # The Turn's acknowledgement, not its admission deadline, retires the input it owns.
    await wait_until(lambda: listening.records("input.retired"), "the input was never retired")
    (retired,) = listening.records("input.retired")
    assert retired["input_id"] == turn["input_id"] and not listening.records(
        "input.admission_expired"
    )
    # Bounded metadata only: neither raw identities nor recognized text leave the process.
    serialized = json.dumps(runtime.perception.input_trace.snapshot().to_dict())
    assert "segment-a" not in serialized and "private words" not in serialized
    assert len(records) <= runtime.perception.input_trace.policy.max_records


def waited(listening: Listening, record: dict) -> float:
    """Seconds from the hold that began the input's transcript wait to the record."""
    (hold,) = (r for r in listening.records("input.decision") if r["action"] == "hold")
    return (record["recorded_time_ns"] - hold["recorded_time_ns"]) / 1e9


@pytest.mark.parametrize("listening", [{"settings": {"transcript_wait_sec": WAIT}}], indirect=True)
async def test_a_final_later_than_the_transcript_wait_still_commits_before_the_deadline(
    listening: Listening,
) -> None:
    # KD-17: the wait is a point of observation, not a cutoff. Real segment STT finals came
    # 0.9-1.1 s after it began; the input must keep waiting and commit with them.
    defaults = TurnTakingConfig()
    assert (defaults.transcript_wait_sec, defaults.transcript_timeout_sec) == (WAIT, DEADLINE)
    listening.utter(listening.speech(), "segment-a")
    await wait_until(lambda: listening.records("input.transcript_wait"), "no wait observed")
    (stream,) = listening.stt.streams
    stream.emit(TranscriptionEventType.FINAL_TRANSCRIPT, "segment-a", "slow words")
    await wait_until(
        lambda: any(d.action == TurnTakingAction.COMMIT for _, d in listening.decisions()),
        "the slowly transcribed input never committed",
    )

    (pending,) = listening.records("input.transcript_wait")
    assert (pending["outcome"], pending["missing_count"]) == ("pending", 1)
    commit = next(r for r in listening.records("input.decision") if r["action"] == "commit")
    assert WAIT <= waited(listening, pending) < waited(listening, commit) < DEADLINE
    (transcript,) = listening.transcripts()
    _, decision = next(item for item in listening.decisions() if item[1].action == "commit")
    assert transcript.observation_id in decision.input_observation_ids
    assert TurnTakingAction.CANCEL not in [d.action for _, d in listening.decisions()]
    assert not listening.records("input.transcript_rejected")


@pytest.mark.parametrize("listening", [{"settings": {"transcript_wait_sec": WAIT}}], indirect=True)
async def test_late_stt_final_after_transcript_timeout_never_revives_the_input(
    listening: Listening,
) -> None:
    listening.utter(listening.speech(), "segment-a")
    await wait_until(
        lambda: any(d.reason == "transcript_timeout" for _, d in listening.decisions()),
        "the untranscribed input was never cancelled",
    )
    (stream,) = listening.stt.streams
    stream.emit(TranscriptionEventType.FINAL_TRANSCRIPT, "segment-a", "too late")
    await wait_until(lambda: listening.records("input.transcript_rejected"), "no rejection")

    # Only the hard deadline cancels: the wait was observed first, then the deadline passed.
    (pending,) = listening.records("input.transcript_wait")
    cancel = next(r for r in listening.records("input.decision") if r["action"] == "cancel")
    assert WAIT <= waited(listening, pending) < DEADLINE <= waited(listening, cancel)
    # The recognition result is real evidence, but its retired input stays cancelled.
    assert len(listening.transcripts()) == 1
    actions = [decision.action for _, decision in listening.decisions()]
    assert TurnTakingAction.COMMIT not in actions and actions[-1] == TurnTakingAction.CANCEL
    (rejected,) = listening.records("input.transcript_rejected")
    (closed,) = listening.records("speech.close")
    assert (rejected["reason"], rejected["segment_id"]) == ("retired_segment", closed["segment_id"])
    assert listening.runtime.turn.latest is None


@pytest.mark.parametrize("listening", [{"settings": {"transcript_wait_sec": WAIT}}], indirect=True)
async def test_after_the_deadline_the_source_speaks_again_and_the_late_final_stays_its_own(
    listening: Listening,
) -> None:
    # KD-17 recovery in one session: the first utterance is retired at the hard deadline;
    # the same source speaks again and that turn commits, while the first one's final,
    # arriving late, is refused as its own retired segment's and joins nothing.
    source = listening.speech()
    listening.utter(source, "segment-a")
    await wait_until(
        lambda: any(d.reason == "transcript_timeout" for _, d in listening.decisions()),
        "the untranscribed input was never cancelled",
    )
    listening.utter(source, "segment-b")
    (stream,) = listening.stt.streams
    await wait_until(lambda: stream.committed == ["segment-a", "segment-b"], "no second commit")
    stream.emit(TranscriptionEventType.FINAL_TRANSCRIPT, "segment-a", "too late")
    stream.emit(TranscriptionEventType.FINAL_TRANSCRIPT, "segment-b", "second words")
    await wait_until(
        lambda: any(d.action == TurnTakingAction.COMMIT for _, d in listening.decisions()),
        "the second utterance never committed",
    )

    first, second = listening.records("speech.close")
    (rejected,) = listening.records("input.transcript_rejected")
    assert (rejected["reason"], rejected["segment_id"]) == ("retired_segment", first["segment_id"])
    late, own = sorted(listening.transcripts(), key=lambda o: o.segment.segment_id)
    assert (late.segment.segment_id, own.segment.segment_id) == ("segment-a", "segment-b")
    (_, commit), *more = [item for item in listening.decisions() if item[1].action == "commit"]
    # The commit carries the second utterance's own final, never the late one.
    assert not more and own.observation_id in commit.input_observation_ids
    assert late.observation_id not in commit.input_observation_ids
    accepted = [r for r in listening.records() if r.get("state") == "final"]
    assert [r["segment_id"] for r in accepted] == [second["segment_id"]]
    actions = [d.action for _, d in listening.decisions()]
    assert actions.count(TurnTakingAction.CANCEL) == 1


SPAN, LAG = 0.2, 0.05  # A hold or addressing wait short enough for a test; a late start


def terminal(listening: Listening) -> dict:
    (record,) = (
        r for r in listening.records("input.decision") if r["action"] in ("commit", "cancel")
    )
    return record


@pytest.mark.parametrize(
    ("listening", "stage", "reason"),
    [
        (
            {"model": EndpointModel(0.0, lag=LAG), "settings": {"max_hold_sec": SPAN}},
            "input.hold",
            "turn_hold_timeout",
        ),
        (
            {"model": EndpointModel(fails=True, lag=LAG), "settings": {"max_hold_sec": SPAN}},
            "input.hold",
            "assessment_error_timeout",
        ),
        (
            {
                "model": EndpointModel(lag=LAG),
                "addressing": ("semantic",),
                "settings": {"addressing_wait_sec": SPAN},
            },
            "input.addressing_wait",
            None,
        ),
    ],
    indirect=["listening"],
    ids=["hold", "assessment-failed", "addressing"],
)
async def test_each_wait_between_a_transcript_and_its_turns_decision_is_traced_as_a_span(
    listening: Listening, stage: str, reason: str | None
) -> None:
    # O-16: the endpoint model's assessment, queued when the transcript came, then the hold
    # or addressing wait it led to, each with its span, all before the decision.
    listening.utter(listening.speech(), "segment-a")
    await wait_until(lambda: listening.stt.streams, "the source never opened")
    (stream,) = listening.stt.streams
    stream.emit(TranscriptionEventType.FINAL_TRANSCRIPT, "segment-a", "words")
    await wait_until(lambda: listening.records(stage), "the wait was never traced")
    await wait_until(
        lambda: any(d.action == TurnTakingAction.COMMIT for _, d in listening.decisions()),
        "the input never committed",
    )

    (accepted,) = listening.records("input.transcript")
    (assessed,) = listening.records("input.assessment")
    (waited,) = listening.records(stage)
    # Queued as its transcript came, it started once the loop let it.
    assert accepted["recorded_time_ns"] <= assessed["event_time_ns"]
    assert assessed["start_time_ns"] - assessed["event_time_ns"] >= LAG * 1e9
    assert assessed["end_time_ns"] <= waited["start_time_ns"]
    assert waited["end_time_ns"] - waited["start_time_ns"] >= SPAN * 1e9
    assert waited["end_time_ns"] <= terminal(listening)["recorded_time_ns"]
    assert assessed["outcome"] == ("failed" if reason == "assessment_error_timeout" else "done")
    assert (waited["outcome"], waited.get("reason")) == ("done", reason)


@pytest.mark.parametrize(
    "listening",
    [{"model": EndpointModel(0.0, transcript=False), "settings": {"max_hold_sec": HANG_GUARD}}],
    indirect=True,
)
async def test_a_hold_its_speaker_ends_by_speaking_on_is_traced_as_cancelled(
    listening: Listening,
) -> None:
    source = listening.speech()
    listening.utter(source, "segment-a")
    await wait_until(
        lambda: any(d.reason == "endpoint_incomplete" for _, d in listening.decisions()),
        "the input never held",
    )
    listening.frame(source, "segment-b", 1)  # The speaker goes on.
    await wait_until(lambda: listening.records("input.hold"), "the hold never ended")
    (hold,) = listening.records("input.hold")
    assert (hold["outcome"], hold["reason"]) == ("cancelled", "turn_hold_timeout")
    assert hold["end_time_ns"] - hold["start_time_ns"] < HANG_GUARD * 1e9


async def test_stale_source_generation_retires_its_stream_frames_and_late_results(
    listening: Listening,
) -> None:
    old, new = listening.speech(1), listening.speech(2)
    listening.frame(old, "segment-a", 1)
    listening.frame(old, "segment-a", 2)
    await wait_until(lambda: listening.stt.streams, "the first source never opened")
    listening.frame(new, "segment-b", 1)
    await wait_until(lambda: len(listening.stt.streams) == 2, "the new generation never opened")
    first, second = listening.stt.streams
    await wait_until(lambda: first.closed, "the retired generation kept its provider stream")

    # A late frame and a late result from the retired generation reach nothing downstream.
    listening.frame(old, "segment-a", 3)
    first.emit(TranscriptionEventType.FINAL_TRANSCRIPT, "segment-a", "stale words")
    listening.frame(new, "segment-b", 2)
    listening.close(new, "segment-b")
    await wait_until(lambda: second.committed == ["segment-b"], "the new segment never committed")
    second.emit(TranscriptionEventType.FINAL_TRANSCRIPT, "segment-b", "fresh words")
    await wait_until(listening.transcripts, "the current generation was never transcribed")

    assert first.frames == {"segment-a": 2} and second.frames == {"segment-b": 2}
    assert [item.payload.text for item in listening.transcripts()] == ["fresh words"]
    ignored = listening.records("perception.speech_ignored")
    assert [record["reason"] for record in ignored] == ["source_generation_retired"]
    retired = [r for r in listening.records("stt.terminal") if r["outcome"] == "cancelled"]
    assert [record["reason"] for record in retired] == ["source_generation_retired"]


async def test_duplicate_late_and_gapped_frames_never_reach_the_provider(
    listening: Listening,
) -> None:
    source = listening.speech()
    listening.utter(source, "segment-a", frames=2)
    listening.frame(source, "segment-a", 3)  # Late: the segment already closed.
    listening.frame(source, "segment-b", 1)
    listening.frame(source, "segment-b", 1)  # Duplicate route index.
    listening.frame(source, "segment-b", 3)  # Gap: index 2 never arrived.
    await wait_until(lambda: listening.records("stt.terminal"), "the gap was never detected")
    await wait_until(lambda: listening.stt.streams[0].closed, "a gapped stream stayed open")

    (stream,) = listening.stt.streams
    assert stream.frames == {"segment-a": 2, "segment-b": 1}
    assert stream.committed == ["segment-a"]
    (late,) = listening.records("perception.speech_ignored")
    assert late["reason"] == "segment_terminal"
    outcomes = {(r["outcome"], r["reason"]) for r in listening.records("stt.terminal")}
    assert ("rejected", "frame_gap") in outcomes and ("cancelled", "frame_gap") in outcomes


async def test_recognition_after_its_segment_retired_is_stale_on_a_live_stream(
    listening: Listening,
) -> None:
    source = listening.speech()
    listening.utter(source, "segment-a")
    await wait_until(
        lambda: listening.stt.streams and listening.stt.streams[0].committed, "no commit"
    )
    (stream,) = listening.stt.streams
    stream.emit(TranscriptionEventType.ERROR, "segment-a", reason_code="input_flushed")
    stream.emit(TranscriptionEventType.FINAL_TRANSCRIPT, "segment-a", "after the flush")
    listening.utter(source, "segment-b")
    await wait_until(
        lambda: stream.committed == ["segment-a", "segment-b"], "stream did not survive"
    )
    stream.emit(TranscriptionEventType.FINAL_TRANSCRIPT, "segment-b", "kept words")
    await wait_until(listening.transcripts, "the live stream stopped transcribing")

    assert [item.payload.text for item in listening.transcripts()] == ["kept words"]
    (stale,) = listening.records("stt.stale")
    assert stale["reason"] == "segment_retired"
    assert not stream.closed


async def test_cancelled_speech_epoch_cancels_its_input_and_ignores_later_frames(
    listening: Listening,
) -> None:
    runtime, source = listening.runtime, listening.speech()
    listening.frame(source, "segment-a", 1)
    listening.frame(source, "segment-a", 2)
    await wait_until(lambda: listening.stt.streams, "the source never opened")
    runtime.perception.publish_observation(
        EnvObservation.speech_cancelled(
            reason=SpeechCancellationReason.SOURCE_MUTED,
            time_range=runtime.clock.point(),
            source=source,
            segment=PerceptionSegmentRef(source, "segment-a"),
            metadata={"input_source": MICROPHONE},
        )
    )
    await wait_until(
        lambda: any(d.reason == "source_muted" for _, d in listening.decisions()),
        "the open input was not cancelled",
    )
    (stream,) = listening.stt.streams
    await wait_until(lambda: stream.closed, "the cancelled epoch kept its provider stream")
    listening.frame(source, "segment-a", 3)
    listening.frame(source, "segment-c", 1)

    assert stream.frames == {"segment-a": 2} and len(listening.stt.streams) == 1
    assert [d.action for _, d in listening.decisions()][-1] == TurnTakingAction.CANCEL
    reasons = [record["reason"] for record in listening.records("perception.speech_ignored")]
    assert reasons == ["segment_terminal", "speech_source_cancelled"]
    assert runtime.turn.latest is None
