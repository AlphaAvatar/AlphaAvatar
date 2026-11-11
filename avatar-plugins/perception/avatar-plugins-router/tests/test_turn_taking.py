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
"""Turn taking over one temporal input window, offline: what joins an input, what seals it, and
what an acknowledgement, a cancellation, a gap or a deadline retires. Each observation is handed
to the coordinator as it is published, so every ordering below is the test's own."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from alphaavatar.agents.configs.runtime_config import RuntimeConfig
from alphaavatar.agents.router.enums import (
    AddressingEvidenceKind,
    AddressingMode,
    AssessmentLabel,
    InteractionEntityKind,
    TurnTakingAction,
    TurnTakingMode,
)
from alphaavatar.agents.router.models import TurnTakingModelBase, TurnTakingModelCapabilities
from alphaavatar.agents.router.schemas import (
    InteractionAddressingEvidence,
    InteractionEntityRef,
    TurnTakingAssessment,
    TurnTakingDecision,
    TurnTakingEvidence,
)
from alphaavatar.agents.runtime import AvatarRuntime, StateRuntime
from alphaavatar.agents.runtime.inference import InferenceExecutor
from alphaavatar.agents.workspace import WorkspacePaths
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.env.enums import AnnotationKind, SpeechCancellationReason
from alphaavatar.core.env.schemas import (
    PerceptionEntityRef,
    PerceptionSegmentRef,
    PerceptionSourceRef,
)
from alphaavatar.core.media import AudioFrame, AudioFramePayload, AudioSegmentPayload, TextPayload
from alphaavatar.core.perception.enums import PerceptionStreamKind
from alphaavatar.core.session import SessionRuntime
from alphaavatar.core.time import RuntimeTimeRange
from alphaavatar.core.turn.enums import TurnInputModality
from alphaavatar.core.turn.schemas import TurnNotice
from alphaavatar.plugins.router.processors.turn_taking.assessment import AssessmentWork
from alphaavatar.plugins.router.processors.turn_taking.config import TurnTakingConfig
from alphaavatar.plugins.router.processors.turn_taking.coordinator import TurnTakingCoordinator
from alphaavatar.plugins.router.processors.turn_taking.fusion import AddressingFusion
from alphaavatar.plugins.router.processors.turn_taking.models.smart_turn_v3 import SmartTurnV3Model
from alphaavatar.plugins.router.processors.turn_taking.policy import TurnTakingPolicy

HANG_GUARD = 10
SPEECH = "router:speech:microphone"
TRANSCRIPTS = PerceptionSourceRef("router:transcript:microphone", 1)
MICROPHONE = {"source_id": "microphone", "source_generation": 1}
NOTICE = "voice.transcription_unavailable"
SEMANTIC = "router.addressing.semantic"
ALICE, BOB = PerceptionEntityRef("voice-alice"), PerceptionEntityRef("voice-bob")
HOLD, COMMIT, CANCEL = TurnTakingAction.HOLD, TurnTakingAction.COMMIT, TurnTakingAction.CANCEL
CONSUMER, STREAMS = "test.turn_taking", {PerceptionStreamKind.SPEECH, PerceptionStreamKind.TEXT}


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


class Model(TurnTakingModelBase):
    """Offline turn-taking model: an input's speech is complete unless its last segment
    ``continues``, a clear judgment either way.
    With ``transcript`` it assesses the words, as a text model would; without, the sound alone,
    as Smart Turn does. Each assessment waits for ``gate``; a ``stubborn`` one answers even when
    cancelled, as a model that cannot stop would."""

    def __init__(
        self, *, continues: tuple[str, ...] = (), transcript: bool = True, stubborn: bool = False
    ) -> None:
        self.continues, self.transcript, self.stubborn = frozenset(continues), transcript, stubborn
        self.gate = asyncio.Event()
        self.gate.set()
        self.assessed: list[TurnTakingEvidence] = []

    @property
    def name(self) -> str:
        return "offline_turn_taking"

    @property
    def capabilities(self) -> TurnTakingModelCapabilities:
        return TurnTakingModelCapabilities(
            modes=frozenset({TurnTakingMode.AUDIO_ONLY}), uses_transcript=self.transcript
        )

    async def assess(self, evidence: TurnTakingEvidence) -> TurnTakingAssessment:
        self.assessed.append(evidence)
        try:
            await self.gate.wait()
        except asyncio.CancelledError:
            if not self.stubborn:
                raise
        complete = evidence.segments[-1].segment_id not in self.continues
        return TurnTakingAssessment(
            input_id=evidence.input_id,
            revision=evidence.revision,
            turn_mode=evidence.turn_mode,
            confidence=1.0,
            speech_completion=AssessmentLabel.POSITIVE if complete else AssessmentLabel.NEGATIVE,
            speech_completion_probability=float(complete),
        )


@dataclass
class Inputs:
    runtime: AvatarRuntime
    model: Model
    coordinator: TurnTakingCoordinator
    source: PerceptionSourceRef

    def _handle(self, observation: EnvObservation) -> None:
        """Published, then read as turn taking reads it: what perception admitted, in order."""
        perception = self.runtime.perception
        perception.publish_observation(observation)
        window = perception.take_pending_observations(consumer_id=CONSUMER, streams=STREAMS)
        for item in window.observations:
            self.coordinator.handle_observation(item)
        perception.commit_observations(window)

    def start(self, segment_id: str, speaker: PerceptionEntityRef | None = None) -> None:
        frame = AudioFramePayload.create(
            frame=AudioFrame(16_000, 1, 160, bytes(320)), frame_id=None
        )
        self._handle(
            EnvObservation.speech_frame(
                time_range=self.runtime.clock.point(),
                source=self.source,
                segment=PerceptionSegmentRef(self.source, segment_id),
                entity=speaker,
                payload=frame,
                metadata={"route_index": 1, "speech_event": "start", "input_source": MICROPHONE},
            )
        )

    def close(
        self, segment_id: str, speaker: PerceptionEntityRef | None = None, pcm: bytes = b""
    ) -> None:
        """The segment's end; with ``pcm``, its sound, ending now."""
        now, payload = self.runtime.clock.now(), None
        if pcm:
            payload = AudioSegmentPayload.create(
                segment_id=segment_id,
                pcm16_bytes=pcm,
                sample_rate=16_000,
                num_channels=1,
                samples_per_channel=len(pcm) // 2,
                source_observation_ids=(),
            )
        self._handle(
            EnvObservation.speech_segment(
                time_range=RuntimeTimeRange(now.shifted(-len(pcm) / 32_000), now),
                source=self.source,
                segment=PerceptionSegmentRef(self.source, segment_id),
                entity=speaker,
                payload=payload,
                metadata={"speech_event": "end", "input_source": MICROPHONE},
            )
        )

    def say(
        self, segment_id: str, speaker: PerceptionEntityRef | None = None, pcm: bytes = b""
    ) -> None:
        self.start(segment_id, speaker)
        self.close(segment_id, speaker, pcm)

    def final(self, segment_id: str, text: str, source: PerceptionSourceRef | None = None) -> None:
        self._handle(
            EnvObservation.transcript_segment(
                time_range=self.runtime.clock.point(),
                source=TRANSCRIPTS,
                segment=PerceptionSegmentRef(source or self.source, segment_id),
                payload=TextPayload.create(text=text),
            )
        )

    def addressed(self, segment_id: str) -> None:
        """Semantic addressing's evidence for the segment's transcript: to the Avatar."""
        (transcript,) = (
            item
            for item in self.runtime.perception.text.read_range(after_seq=0).items
            if item.segment == PerceptionSegmentRef(self.source, segment_id)
        )
        evidence = InteractionAddressingEvidence(
            evidence_kind=AddressingEvidenceKind.SEMANTIC,
            speaker=InteractionEntityRef(kind=InteractionEntityKind.PERSON, source=self.source),
            addressees=(InteractionEntityRef(kind=InteractionEntityKind.AVATAR),),
            addressing_mode=AddressingMode.DIRECT,
            confidence=0.98,
            label=AssessmentLabel.POSITIVE,
        )
        annotation = evidence.to_annotation(
            source=SEMANTIC, observation_id=transcript.observation_id
        )
        self.coordinator.handle_annotation(self.runtime.perception.publish_annotation(annotation))

    def cancel(self, segment_id: str) -> None:
        self._handle(
            EnvObservation.speech_cancelled(
                reason=SpeechCancellationReason.SOURCE_MUTED,
                time_range=self.runtime.clock.point(),
                source=self.source,
                segment=PerceptionSegmentRef(self.source, segment_id),
                metadata={"input_source": MICROPHONE},
            )
        )

    def published(self) -> list[tuple[object, TurnTakingDecision]]:
        events = self.runtime.perception.annotation_events.read_range(after_seq=0).items
        return [
            (event, TurnTakingDecision.from_annotation(event.annotation))
            for event in events
            if event.annotation.kind == AnnotationKind.INTERACTION_TURN
        ]

    def decisions(
        self, action: TurnTakingAction, reason: str | None = None
    ) -> list[TurnTakingDecision]:
        return [
            decision
            for _, decision in self.published()
            if decision.action == action and reason in (None, decision.reason)
        ]

    def traced(self, identity: str) -> str:
        """An identity as the input trace records it."""
        return self.runtime.perception.input_trace.identity(identity)

    def records(self, stage: str) -> list[dict]:
        records = self.runtime.perception.input_trace.snapshot().to_dict()["records"]
        return [record for record in records if record["stage"] == stage]

    def texts(self, decision: TurnTakingDecision) -> list[str]:
        timeline = self.runtime.perception.timeline
        found = [timeline.get_observation(observation_id=i) for i in decision.input_observation_ids]
        return [item.payload.text for item in found if isinstance(item.payload, TextPayload)]

    def acknowledge(self, decision: TurnTakingDecision) -> None:
        """Engine's admission of the decision: its Turn, frozen at the decision's cutoff."""
        event = next(event for event, item in self.published() if item == decision)
        snapshot = self.runtime.turn.commit_event_input(
            input_id=decision.input_id,
            modality=TurnInputModality.AUDIO,
            text=" ".join(self.texts(decision)),
            started_at=event.time_range.start,
            committed_at=event.time_range.end,
            cutoff_sequence=event.sequence,
            input_observation_ids=decision.input_observation_ids,
        )
        self.coordinator.handle_turn(snapshot)


@pytest.fixture
async def inputs(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Inputs]:
    """The coordinator; ``request.param`` may give its ``model`` and turn-taking ``settings``.
    A hold never times out unless a test lets it."""
    param = getattr(request, "param", {})
    runtime, model = avatar_runtime(tmp_path / "workspace"), Model(**param.get("model", {}))
    coordinator = TurnTakingCoordinator(
        runtime=runtime,
        model=model,
        policy=TurnTakingPolicy(),
        fusion=AddressingFusion(),
        config=TurnTakingConfig(
            **{"speech_completion_wait_sec": HANG_GUARD} | param.get("settings", {})
        ),
        transcript_timeout_notice_code=NOTICE,
    )
    yield Inputs(runtime, model, coordinator, runtime.perception.next_source(SPEECH))
    model.gate.set()
    await coordinator.reset()
    await runtime.aclose()


@pytest.mark.parametrize("inputs", [{"model": {"continues": ("segment-a",)}}], indirect=True)
@pytest.mark.parametrize(
    ("first", "second"),
    [(None, None), (ALICE, ALICE), (ALICE, BOB), (ALICE, None)],
    ids=["unnamed", "one-speaker", "two-speakers", "named-then-unnamed"],
)
async def test_a_held_input_goes_on_across_segments_whoever_they_name(
    inputs: Inputs, first: PerceptionEntityRef | None, second: PerceptionEntityRef | None
) -> None:
    inputs.say("segment-a", first)
    inputs.final("segment-a", "What is two plus")
    await wait_until(lambda: inputs.decisions(HOLD, "speech_incomplete"), "it never held")
    inputs.say("segment-b", second)
    inputs.final("segment-b", "three?")
    await wait_until(lambda: inputs.decisions(COMMIT), "the input never committed")

    # One input: speaker labels are its actors, never a boundary of it.
    (hold,) = inputs.decisions(HOLD, "speech_incomplete")
    (commit,) = inputs.decisions(COMMIT)
    assert commit.input_id == hold.input_id and commit.revision > hold.revision
    assert inputs.texts(commit) == ["What is two plus", "three?"]
    assert [actor.entity for actor in commit.actors] == list(dict.fromkeys((first, second)))


@pytest.mark.parametrize("inputs", [{"model": {"transcript": False}}], indirect=True)
@pytest.mark.parametrize("acknowledged", [False, True], ids=["unacknowledged", "acknowledged"])
async def test_an_input_sealed_for_its_words_leaves_the_next_one_heard_and_decided(
    inputs: Inputs, acknowledged: bool
) -> None:
    # Speech completion is decided on the sound; the words are still due when the next input begins.
    inputs.say("segment-a")
    waiting = "awaiting_transcript_for_commit"
    await wait_until(lambda: inputs.decisions(HOLD, waiting), "the first input never sealed")
    (sealed,) = inputs.decisions(HOLD, waiting)
    inputs.say("segment-b")
    inputs.final("segment-b", "And the weather?")
    await wait_until(lambda: inputs.decisions(COMMIT), "the next input never committed")
    (second,) = inputs.decisions(COMMIT)
    assert second.input_id != sealed.input_id and inputs.texts(second) == ["And the weather?"]

    if acknowledged:
        inputs.acknowledge(second)
    inputs.final("segment-a", "What is two plus three?")
    if acknowledged:
        # The acknowledged Turn's evidence begins after the sealed input's: that input is
        # superseded, its words joining nothing.
        await wait_until(
            lambda: inputs.decisions(CANCEL, "superseded_transcript"), "it was never superseded"
        )
        (cancel,) = inputs.decisions(CANCEL, "superseded_transcript")
        assert cancel.input_id == sealed.input_id and inputs.decisions(COMMIT) == [second]
    else:
        # Nothing has committed ahead of it: its own words arrive within its own budget.
        await wait_until(lambda: len(inputs.decisions(COMMIT)) == 2, "the sealed input was lost")
        first = inputs.decisions(COMMIT)[1]
        assert first.input_id == sealed.input_id
        assert inputs.texts(first) == ["What is two plus three?"]


@pytest.mark.parametrize("inputs", [{"model": {"stubborn": True}}], indirect=True)
async def test_an_assessment_answering_after_its_cancellation_decides_nothing(
    inputs: Inputs,
) -> None:
    inputs.model.gate.clear()
    inputs.say("segment-a")
    inputs.final("segment-a", "What is two plus")
    await wait_until(lambda: inputs.model.assessed, "the input was never assessed")
    inputs.start("segment-b")  # The speaker goes on: the assessment is cancelled, and answers.
    await wait_until(lambda: inputs.records("input.assessment"), "the assessment never ended")
    assert not inputs.decisions(COMMIT)

    inputs.close("segment-b")
    inputs.final("segment-b", "three?")
    inputs.model.gate.set()
    await wait_until(lambda: inputs.decisions(COMMIT), "the input never committed")
    (commit,) = inputs.decisions(COMMIT)
    assert inputs.texts(commit) == ["What is two plus", "three?"]
    assert commit.revision > inputs.model.assessed[0].revision


@pytest.mark.parametrize(
    "inputs",
    [
        {
            "settings": {
                "transcript_wait_sec": 0.05,
                "transcript_timeout_sec": 0.2,
                "speech_completion_wait_sec": 0.05,
            }
        }
    ],
    indirect=True,
)
async def test_a_final_handled_past_its_deadline_is_late_though_the_deadline_timer_never_ran(
    inputs: Inputs,
) -> None:
    inputs.say("segment-a")
    waiting = "awaiting_transcript_for_assessment"
    await wait_until(lambda: inputs.decisions(HOLD, waiting), "the input never waited")
    time.sleep(0.25)  # The loop is held past the deadline: its timer is due, and has not run.
    inputs.final("segment-a", "Too late.")
    await wait_until(lambda: inputs.decisions(COMMIT), "the untranscribed input never ended")

    # It is the notice's Turn: the words came after the deadline, whatever ran first. Without
    # them the text model cannot judge completion, which its own wait then settles, said too.
    (commit,) = inputs.decisions(COMMIT)
    assert (commit.reason, commit.system_notices) == (
        "transcript_timeout",
        (TurnNotice("router.speech_completion_uncertain"), TurnNotice(NOTICE, ("segment-a",))),
    )
    assert inputs.texts(commit) == []
    assert not [r for r in inputs.records("input.transcript") if r["state"] == "final"]


@pytest.mark.parametrize(
    "inputs",
    [{"settings": {"transcript_wait_sec": 0.05, "transcript_timeout_sec": 0.4}}],
    indirect=True,
)
async def test_speech_joining_a_waiting_input_keeps_its_own_transcript_budget(
    inputs: Inputs,
) -> None:
    inputs.say("segment-a")  # Its final never comes.
    waiting = "awaiting_transcript_for_assessment"
    await wait_until(lambda: inputs.decisions(HOLD, waiting), "the input never waited")
    await asyncio.sleep(0.3)
    inputs.say("segment-b")  # It joins the input 0.1 s before the first segment's deadline.
    await asyncio.sleep(0.2)
    inputs.final("segment-b", "three?")  # Past that deadline, within its own.
    await wait_until(lambda: inputs.decisions(COMMIT), "the input never committed")

    (commit,) = inputs.decisions(COMMIT)
    assert inputs.texts(commit) == ["three?"]
    assert commit.system_notices == (TurnNotice(NOTICE, ("segment-a",)),)


@pytest.mark.parametrize(
    "inputs",
    [{"model": {"transcript": False}, "settings": {"max_pending_inputs": 1}}],
    indirect=True,
)
@pytest.mark.parametrize(
    "retire", ["source-cancelled", "new-generation", "perception-gap", "capacity"]
)
async def test_a_sealed_input_retired_by_its_source_or_a_bound_takes_no_late_words(
    inputs: Inputs, retire: str
) -> None:
    inputs.say("segment-a")
    waiting = "awaiting_transcript_for_commit"
    await wait_until(lambda: inputs.decisions(HOLD, waiting), "the input never sealed")
    (sealed,) = inputs.decisions(HOLD, waiting)
    old = inputs.source
    if retire == "source-cancelled":
        inputs.start("segment-b")
        inputs.cancel("segment-b")  # Muted: every input of the source ends with it.
        inputs.source = inputs.runtime.perception.next_source(SPEECH)
    elif retire == "new-generation":
        inputs.source = inputs.runtime.perception.next_source(SPEECH)
        inputs.start("segment-c")  # The device reopened, and its new generation speaks.
    elif retire == "perception-gap":
        await inputs.coordinator.reset(retain_retired=True)
    elif retire == "capacity":
        inputs.say("segment-b")  # A second sealed input is one more than the bound.
        await wait_until(lambda: inputs.decisions(CANCEL), "the bound was never kept")

    inputs.final("segment-a", "Late words.", source=old)
    ended = [d.reason for d in inputs.decisions(CANCEL) if d.input_id == sealed.input_id]
    rejected = [r["reason"] for r in inputs.records("input.transcript_rejected")]
    retired = [
        r
        for r in inputs.records("input.retired")
        if r["input_id"] == inputs.traced(sealed.input_id)
    ]
    assert {
        "source-cancelled": (["source_muted"], ["retired_segment"]),
        "new-generation": ([], []),  # Its source is no longer current: it ends unannounced.
        "perception-gap": ([], ["retired_segment"]),
        "capacity": (["pending_capacity"], ["retired_segment"]),
    }[retire] == (ended, rejected)
    assert retired

    # The next input is heard, sealed and decided on its own words alone.
    inputs.say("segment-c")
    inputs.final("segment-c", "Fresh words.")
    await wait_until(lambda: inputs.decisions(COMMIT), "the next input never committed")
    (commit,) = inputs.decisions(COMMIT)
    assert inputs.texts(commit) == ["Fresh words."]


@pytest.mark.parametrize("inputs", [{"settings": {"commit_timeout_sec": 0.2}}], indirect=True)
@pytest.mark.parametrize("acknowledgement", ["never", "delayed", "after-expiry"])
async def test_an_acknowledgement_retires_only_the_input_it_owns(
    inputs: Inputs, acknowledgement: str
) -> None:
    inputs.say("segment-a")
    inputs.final("segment-a", "What is two plus three?")
    await wait_until(lambda: inputs.decisions(COMMIT), "the input never committed")
    (first,) = inputs.decisions(COMMIT)
    inputs.start("segment-b")  # The next input begins before Engine has answered.
    if acknowledgement == "delayed":
        inputs.acknowledge(first)
    else:  # Never admitted, as when Engine rejects it; or admitted after its own deadline.
        expired = "input.admission_expired"
        await wait_until(lambda: inputs.records(expired), "the proposal never expired")
        if acknowledgement == "after-expiry":
            inputs.acknowledge(first)

    inputs.close("segment-b")
    inputs.final("segment-b", "And the weather?")
    await wait_until(lambda: len(inputs.decisions(COMMIT)) == 2, "the next input was lost")
    second = inputs.decisions(COMMIT)[1]
    assert second.input_id != first.input_id and inputs.texts(second) == ["And the weather?"]
    assert (
        len(
            [
                r
                for r in inputs.records("input.retired")
                if r["input_id"] == inputs.traced(first.input_id)
            ]
        )
        == 1
    )


class Inference:
    """The Smart Turn runner: each sound it heard; an ending for the second sound on."""

    def __init__(self) -> None:
        self.heard: list[bytes] = []

    async def do_inference(self, method: str, data: bytes) -> bytes:
        self.heard.append(data)
        return np.float32(0.2 if len(self.heard) == 1 else 0.9).tobytes()


async def test_smart_turn_hears_each_sound_once_however_often_its_input_is_reassessed(
    tmp_path: Path,
) -> None:
    # O-16: a transcript or addressing evidence re-decides the input on the same sound; only
    # new speech makes it listen again, and each decision is still its current revision's.
    runtime, inference = avatar_runtime(tmp_path / "workspace"), Inference()
    coordinator = TurnTakingCoordinator(
        runtime=runtime,
        model=SmartTurnV3Model(
            inference_executor=inference, incomplete_threshold=0.3, complete_threshold=0.7
        ),
        policy=TurnTakingPolicy(),
        fusion=AddressingFusion(),
        config=TurnTakingConfig(
            speech_completion_wait_sec=HANG_GUARD, addressing_wait_sec=HANG_GUARD
        ),
        required_addressing_sources=(SEMANTIC,),
    )
    inputs = Inputs(runtime, None, coordinator, runtime.perception.next_source(SPEECH))
    tone = np.full(16_000, 1000, dtype="<i2").tobytes()

    def held(reason: str, count: int = 1) -> Callable[[], bool]:
        return lambda: len(inputs.decisions(HOLD, reason)) >= count

    # The first sound is incomplete: held on it again as its words and addressing arrive.
    inputs.say("segment-a", pcm=tone)
    await wait_until(held("speech_incomplete"), "it was never assessed")
    inputs.final("segment-a", "What is two")
    await wait_until(held("speech_incomplete", 2), "its words never reassessed it")
    inputs.addressed("segment-a")
    await wait_until(held("speech_incomplete", 3), "its addressing never reassessed it")
    # The next sound completes it: decided once its words, then their addressing, are in.
    inputs.say("segment-b", pcm=tone[::-1])
    await wait_until(held("awaiting_transcript_for_addressing"), "it never waited for words")
    inputs.final("segment-b", "plus three?")
    await wait_until(held("addressing_unknown"), "it never waited for its addressing")
    inputs.addressed("segment-b")
    await wait_until(lambda: inputs.decisions(COMMIT), "the input never committed")

    assessed = inputs.records("input.assessment")
    assert len(inference.heard) == 2 and len(assessed) >= 5
    (commit,) = inputs.decisions(COMMIT)
    assert (commit.reason, commit.system_notices) == ("speech_complete", ())
    assert inputs.texts(commit) == ["What is two", "plus three?"]
    assert commit.revision == max(r["revision"] for r in assessed)
    await coordinator.reset()
    await runtime.aclose()


async def test_assessment_work_keeps_the_current_worker_and_reaps_every_cancelled_one(
    tmp_path: Path,
) -> None:
    runtime = avatar_runtime(tmp_path / "workspace")
    work, release, ended = AssessmentWork(runtime), asyncio.Event(), []

    async def worker(name: str) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()  # Its cleanup outlives its replacement's start.
            ended.append(name)
            raise

    work.start("input-1", lambda: worker("replaced"))
    await asyncio.sleep(0)
    work.start("input-1", lambda: worker("current"))
    await asyncio.sleep(0)
    release.set()
    await wait_until(lambda: ended == ["replaced"], "the replaced worker never ended")
    # Its end did not take the current worker with it: cancelling the input still reaches it.
    work.cancel("input-1")
    await wait_until(lambda: ended == ["replaced", "current"], "the current worker was lost")

    release.clear()
    work.start("input-2", lambda: worker("cleaning"))
    work.start("input-3", lambda: worker("running"))
    await asyncio.sleep(0)
    work.cancel("input-2")
    await asyncio.sleep(0)
    reset = asyncio.create_task(work.reset())
    await asyncio.sleep(0.05)
    assert not reset.done()  # It waits for every worker, the one already cleaning up too.
    release.set()
    await asyncio.wait_for(reset, HANG_GUARD)
    # Cancelled again, a worker in its cleanup would never have finished it.
    assert sorted(ended[2:]) == ["cleaning", "running"]
    await runtime.aclose()
