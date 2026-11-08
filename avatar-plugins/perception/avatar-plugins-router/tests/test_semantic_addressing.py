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
"""Semantic addressing over the temporal input since the last committed Turn, with an offline
model: what each request reads, which transcript each result targets, and what retires speech
from the window. Every request is checked as the model got it."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pytest

from alphaavatar.agents.configs.runtime_config import RuntimeConfig
from alphaavatar.agents.router.enums import (
    SemanticAddressingLabel,
    TurnTakingAction,
    TurnTakingMode,
)
from alphaavatar.agents.router.models import SemanticAddressingModelBase
from alphaavatar.agents.router.schemas import (
    InteractionAddressingEvidence,
    SemanticAddressingRequest,
    SemanticAddressingResult,
    TurnTakingDecision,
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
from alphaavatar.core.media import AudioFrame, AudioFramePayload, TextPayload
from alphaavatar.core.session import SessionRuntime
from alphaavatar.core.time import RuntimeTime, RuntimeTimeRange
from alphaavatar.core.turn.enums import TurnInputModality
from alphaavatar.plugins.router.processors.addressing.semantic import processor as semantic
from alphaavatar.plugins.router.processors.addressing.semantic.config import (
    SemanticAddressingConfig,
)

HANG_GUARD = 10
SPEECH = "router:speech:microphone"
TRANSCRIPTS = PerceptionSourceRef("router:transcript:microphone", 1)
MICROPHONE = {"source_id": "microphone", "source_generation": 1}
ALICE, BOB = PerceptionEntityRef("voice-alice"), PerceptionEntityRef("voice-bob")
AVATAR, OTHER = SemanticAddressingLabel.AVATAR, SemanticAddressingLabel.NON_AVATAR
HOLD = 0.05  # How long each assessment takes when the model is timed


async def wait_until(condition: Callable[[], object], failure: str) -> None:
    try:
        async with asyncio.timeout(HANG_GUARD):
            while not condition():
                await asyncio.sleep(0.001)
    except TimeoutError:
        pytest.fail(failure, pytrace=False)


def to_avatar(texts: list[str]) -> SemanticAddressingLabel:
    """To the Avatar when its name is in what was read, unless the target speaks to John."""
    if texts[-1].startswith("John"):
        return OTHER
    return AVATAR if any("Assistant" in text for text in texts) else OTHER


class Model(SemanticAddressingModelBase):
    """Offline semantic addressing: each request kept as the texts it reads, judged by
    ``to_avatar``. Each assessment takes ``hold``, then waits for ``gate``; a ``stubborn`` one
    answers even when cancelled, as a model that cannot stop would."""

    def __init__(self, *, stubborn: bool = False) -> None:
        self.stubborn, self.hold = stubborn, 0.0
        self.requests: list[list[str]] = []
        self.gate = asyncio.Event()
        self.gate.set()

    @property
    def name(self) -> str:
        return "offline_addressing"

    async def assess(self, request: SemanticAddressingRequest) -> SemanticAddressingResult:
        texts = [segment.text for segment in request.transcript_segments]
        self.requests.append(texts)
        try:
            await asyncio.sleep(self.hold)
            await self.gate.wait()
        except asyncio.CancelledError:
            if not self.stubborn:
                raise
            await self.gate.wait()
        label = to_avatar(texts)
        return SemanticAddressingResult(
            label=label,
            label_0_logit=0.0,
            label_1_logit=0.0,
            p_avatar=0.98 if label == AVATAR else 0.02,
        )


@dataclass
class Speech:
    runtime: AvatarRuntime
    model: Model
    processor: semantic.SemanticAddressingProcessor
    source: PerceptionSourceRef
    origin: RuntimeTime
    spans: dict[str, tuple[float, float]] = field(default_factory=dict)
    closes: dict[str, EnvObservation] = field(default_factory=dict)
    finals: dict[str, EnvObservation] = field(default_factory=dict)

    def at(self, seconds: float) -> RuntimeTime:
        return self.origin.shifted(seconds)

    def start(self, segment_id: str, start: float) -> None:
        frame = AudioFramePayload.create(
            frame=AudioFrame(16_000, 1, 160, bytes(320)), frame_id=None
        )
        self.runtime.perception.publish_observation(
            EnvObservation.speech_frame(
                time_range=RuntimeTimeRange.point(self.at(start)),
                source=self.source,
                segment=PerceptionSegmentRef(self.source, segment_id),
                payload=frame,
                metadata={"route_index": 1, "speech_event": "start", "input_source": MICROPHONE},
            )
        )

    def speak(
        self,
        segment_id: str,
        start: float,
        end: float,
        text: str | None = None,
        speaker: PerceptionEntityRef | None = None,
    ) -> None:
        """A segment of speech from ``start`` to ``end`` seconds of media time; its final
        transcript at once when ``text`` is given."""
        self.start(segment_id, start)
        self.spans[segment_id] = start, end
        close = EnvObservation.speech_segment(
            time_range=RuntimeTimeRange(self.at(start), self.at(end)),
            source=self.source,
            segment=PerceptionSegmentRef(self.source, segment_id),
            entity=speaker,
            metadata={"speech_event": "end", "input_source": MICROPHONE},
        )
        self.runtime.perception.publish_observation(close)
        self.closes[segment_id] = close
        if text is not None:
            self.final(segment_id, text, speaker)

    def final(
        self,
        segment_id: str,
        text: str,
        speaker: PerceptionEntityRef | None = None,
        *,
        again: bool = False,
    ) -> None:
        """The segment's final transcript; ``again``, a repeat of the one it had."""
        start, end = self.spans[segment_id]
        observation = EnvObservation.transcript_segment(
            time_range=RuntimeTimeRange(self.at(start), self.at(end)),
            source=TRANSCRIPTS,
            segment=self.closes[segment_id].segment,
            entity=speaker,
            payload=TextPayload.create(text=text),
        )
        self.runtime.perception.publish_observation(observation)
        if not again:
            self.finals[segment_id] = observation

    def segment(self, segment_id: str) -> PerceptionSegmentRef:
        return self.closes[segment_id].segment

    def commit(self, *segment_ids: str) -> None:
        """Engine's admission of a Turn of these segments, as TurnRuntime acknowledges it."""
        owned = [self.closes[s] for s in segment_ids]
        owned += [self.finals[s] for s in segment_ids if s in self.finals]
        self.runtime.turn.commit_event_input(
            input_id="input-" + "-".join(segment_ids),
            modality=TurnInputModality.AUDIO,
            text=" ".join(self.finals[s].payload.text for s in segment_ids if s in self.finals),
            started_at=self.at(min(self.spans[s][0] for s in segment_ids)),
            committed_at=self.runtime.clock.now(),
            cutoff_sequence=self.runtime.perception.capture_cutoff().sequence,
            input_observation_ids=tuple(item.observation_id for item in owned),
        )

    def propose(self, *segment_ids: str) -> None:
        """Turn taking's proposed COMMIT, which Engine never admits."""
        decision = TurnTakingDecision(
            input_id="proposed",
            revision=1,
            turn_mode=TurnTakingMode.AUDIO_ONLY,
            action=TurnTakingAction.COMMIT,
            confidence=1.0,
            input_observation_ids=tuple(self.finals[s].observation_id for s in segment_ids),
        )
        target = self.finals[segment_ids[-1]].observation_id
        self.runtime.perception.publish_annotation(
            decision.to_annotation(source="router.turn_taking", observation_id=target)
        )

    def judged(self, segment_id: str) -> list[tuple[tuple[str, ...], str, PerceptionEntityRef]]:
        """The segment's results as published: the context each read (by segment), its label
        and the subject it names."""
        names = {o.observation_id: s for s, o in self.finals.items()}
        target = self.finals.get(segment_id)
        events = self.runtime.perception.annotation_events.read_range(after_seq=0).items
        found = []
        for event in events:
            annotation = event.annotation
            if (
                annotation.kind != AnnotationKind.INTERACTION_ADDRESSING_EVIDENCE
                or annotation.source != semantic.SemanticAddressingProcessor.SEMANTIC_SOURCE
                or target is None
                or annotation.observation_id != target.observation_id
            ):
                continue
            evidence = InteractionAddressingEvidence.from_annotation(annotation)
            read = tuple(names.get(i, i) for i in evidence.evidence_observation_ids)
            found.append((read, evidence.evidence_label, evidence.speaker.entity))
        return found


@pytest.fixture
async def speech(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Speech]:
    """The processor; ``request.param`` may give the model's options, the perception limits
    and the history it keeps."""
    param, monkeypatch = getattr(request, "param", {}), pytest.MonkeyPatch()
    model = Model(**param.get("model", {}))
    monkeypatch.setattr(
        semantic, "create_semantic_addressing_model", lambda name, inference_executor: model
    )
    workspace, session = WorkspacePaths.from_root(tmp_path), SessionRuntime(session_id="session")
    runtime = AvatarRuntime.create(
        workspace=workspace,
        session=session,
        session_path=workspace.data.sessions.get(session.session_id, date(2026, 1, 1)),
        state=StateRuntime(),
        config=RuntimeConfig(perception=param.get("perception", {})),
        inference=InferenceExecutor("/unused/inference.sock"),
    )
    config = SemanticAddressingConfig(
        avatar_identities=("Assistant",), history_turns=param.get("history", 2)
    )
    processor = semantic.SemanticAddressingProcessor(runtime=runtime, config=config)
    await processor.start()
    yield Speech(
        runtime, model, processor, runtime.perception.next_source(SPEECH), runtime.clock.now()
    )
    model.gate.set()
    await processor.stop()
    await runtime.aclose()
    monkeypatch.undo()


@pytest.mark.parametrize(
    ("first", "second"),
    [(None, None), (ALICE, ALICE), (ALICE, BOB)],
    ids=["unnamed", "one-speaker", "two-speakers"],
)
async def test_speech_in_two_segments_is_read_together_and_each_result_is_its_own(
    speech: Speech, first: PerceptionEntityRef | None, second: PerceptionEntityRef | None
) -> None:
    # A name in one segment, the question in the next: the second is judged on both.
    speech.speak("a", 0.0, 0.8, "Hey Assistant,", first)
    await wait_until(lambda: speech.judged("a"), "the first segment was never judged")
    speech.speak("b", 1.2, 2.4, "what time is it?", second)
    await wait_until(lambda: speech.judged("b"), "the second segment was never judged")

    assert speech.model.requests == [["Hey Assistant,"], ["Hey Assistant,", "what time is it?"]]
    # Each result targets its own transcript, names its own subject and keeps what it read.
    assert speech.judged("a") == [(("a",), "avatar", first)]
    assert speech.judged("b") == [(("a", "b"), "avatar", second)]


async def test_a_change_of_addressee_is_the_later_segments_alone(speech: Speech) -> None:
    speech.speak("a", 0.0, 1.0, "Assistant, what time is it?")
    await wait_until(lambda: speech.judged("a"), "the first segment was never judged")
    speech.speak("b", 1.4, 2.6, "John, can you pass the salt?")
    await wait_until(lambda: speech.judged("b"), "the second segment was never judged")

    # The later segment speaks to someone else; the earlier one's result stands.
    assert speech.judged("a") == [(("a",), "avatar", None)]
    assert speech.judged("b") == [(("a", "b"), "non_avatar", None)]


async def test_transcripts_out_of_order_repeated_or_identified_late_are_read_in_media_time(
    speech: Speech,
) -> None:
    speech.speak("a", 0.0, 0.8)
    speech.speak("b", 1.2, 2.4)
    speech.final("b", "what time is it?")  # STT answers the later segment first.
    await wait_until(lambda: speech.judged("b"), "the later segment was never judged")
    # Its speaker becomes known after its transcript: later judgments name them.
    participants, segment = speech.runtime.participants, speech.segment("b")
    participants.ensure_entity(segment.source, BOB)
    participants.bind_segment(segment, BOB, token=participants.observe_segment(segment))
    speech.final("a", "Hey Assistant,")
    await wait_until(lambda: len(speech.judged("b")) == 2, "the later segment was not re-judged")
    speech.final("a", "Hey Assistant,", again=True)  # The same words: nothing new to judge.
    await asyncio.sleep(0.05)

    assert speech.model.requests == [
        ["what time is it?"],
        ["Hey Assistant,"],
        ["Hey Assistant,", "what time is it?"],
    ]
    assert speech.judged("a") == [(("a",), "avatar", None)]
    # Its first result, published before the identity, is not rewritten.
    assert speech.judged("b") == [(("b",), "non_avatar", None), (("a", "b"), "avatar", BOB)]


@pytest.mark.parametrize("speech", [{"history": 1}], indirect=True)
async def test_only_a_committed_turn_retires_the_input_it_owns(speech: Speech) -> None:
    speech.speak("a", 0.0, 0.8, "Hey Assistant,")
    speech.speak("b", 1.2, 2.4, "what is the weather?")
    await wait_until(lambda: speech.judged("b"), "the input was never judged")
    speech.propose("a", "b")  # Proposed, never admitted: the window keeps it all.
    speech.speak("c", 3.0, 3.8, "And tomorrow?")
    await wait_until(lambda: speech.judged("c"), "the next segment was never judged")
    assert speech.model.requests[-1] == ["Hey Assistant,", "what is the weather?", "And tomorrow?"]

    speech.commit("a", "b")  # Admitted, late: only what it owns leaves the window.
    await wait_until(lambda: len(speech.judged("c")) == 2, "the rest was not judged again")
    speech.final("b", "what is the weather?", again=True)  # Late, of a committed segment
    speech.speak("d", 4.4, 5.0, "Thanks.")
    await wait_until(lambda: speech.judged("d"), "the segment after the commit was never judged")

    committed = "Hey Assistant, what is the weather?"  # The Turn: one line of history
    assert speech.model.requests[3:] == [
        [committed, "And tomorrow?"],
        [committed, "And tomorrow?", "Thanks."],
    ]
    # The evidence is the window's alone: the committed segments are not this input's.
    assert speech.judged("c")[1] == (("c",), "avatar", None)
    assert speech.judged("d") == [(("c", "d"), "avatar", None)]


@pytest.mark.parametrize("acknowledged", [False, True], ids=["unacknowledged", "acknowledged"])
async def test_a_sealed_inputs_late_transcript_stays_its_own_segments(
    speech: Speech, acknowledged: bool
) -> None:
    speech.speak("a", 0.0, 0.8)  # Its transcript is still due when the next input begins.
    speech.speak("b", 1.2, 2.4, "Assistant, what is the weather?")
    await wait_until(lambda: speech.judged("b"), "the next input was never judged")
    if acknowledged:
        speech.commit("b")
        await asyncio.sleep(0.05)
    speech.final("a", "John, hello.")
    await asyncio.sleep(0.1)

    if acknowledged:
        # The committed Turn began after it ended: superseded, it is not judged.
        assert speech.model.requests == [["Assistant, what is the weather?"]]
        assert speech.judged("a") == []
    else:
        # Its judgment reads what came before it and targets it alone; the later input is
        # judged again with it as context, its result still its own.
        assert speech.judged("a") == [(("a",), "non_avatar", None)]
        assert speech.judged("b") == [(("b",), "avatar", None), (("a", "b"), "avatar", None)]


@pytest.mark.parametrize(
    "speech", [{"model": {"stubborn": True}, "perception": {"text_maxlen": 2}}], indirect=True
)
@pytest.mark.parametrize(
    "retire", ["source-cancelled", "new-generation", "context-switch", "gap", "late-job", "stop"]
)
async def test_what_ends_a_window_ends_its_judgments_late_ones_too(
    speech: Speech, retire: str
) -> None:
    speech.speak("a", 0.0, 0.8, "Hey Assistant,")
    await wait_until(lambda: speech.judged("a"), "the first segment was never judged")
    speech.model.gate.clear()
    speech.speak("b", 1.2, 2.4, "what time is it?")
    await wait_until(lambda: len(speech.model.requests) == 2, "the second was never assessed")
    if retire == "source-cancelled":
        speech.start("c", 3.0)
        speech.runtime.perception.publish_observation(
            EnvObservation.speech_cancelled(
                reason=SpeechCancellationReason.SOURCE_MUTED,
                time_range=RuntimeTimeRange.point(speech.at(3.1)),
                source=speech.source,
                segment=PerceptionSegmentRef(speech.source, "c"),
                metadata={"input_source": MICROPHONE},
            )
        )
        speech.source = speech.runtime.perception.next_source(SPEECH)
    elif retire == "new-generation":
        speech.source = speech.runtime.perception.next_source(SPEECH)
    elif retire == "context-switch":
        speech.runtime.state.context_id = "context-2"
    elif retire == "late-job":
        speech.speak("z", -1.0, -0.5, "Excuse me,")  # Earlier speech, transcribed late
    elif retire == "gap":
        for index, text in enumerate(("One.", "Two.", "Three.")):  # More than the text stream
            speech.speak(f"g{index}", 3.0 + index, 3.5 + index, text)
    else:
        stopping = asyncio.create_task(speech.processor.stop())
        await asyncio.sleep(0.05)
        assert not stopping.done()  # It reaps the job in flight, whose model cannot stop.
    if retire in ("source-cancelled", "new-generation", "context-switch"):
        speech.speak("d", 4.0, 4.6, "Hello.")
    await asyncio.sleep(0.05)
    speech.model.gate.set()  # The held job answers now, cancelled or not.
    await asyncio.sleep(0.1)

    # What it was assessed on is gone: no result reads that window.
    assert (("a", "b"), "avatar", None) not in speech.judged("b")
    if retire == "late-job":
        assert speech.judged("b") == [(("z", "a", "b"), "avatar", None)]
    elif retire == "stop":
        await asyncio.wait_for(stopping, HANG_GUARD)
        assert speech.judged("b") == [] and len(speech.model.requests) == 2
    elif retire == "gap":
        assert speech.judged("b") == []
        assert speech.model.requests[2:] == [["Two."], ["Two.", "Three."]]
    else:
        # A new window: the next speech is read alone.
        assert speech.model.requests[2:] == [["Hello."]]
        assert speech.judged("d") == [(("d",), "non_avatar", None)]


async def test_each_judgment_is_traced_from_when_it_was_queued(speech: Speech) -> None:
    # O-16: the router waits for this evidence after a final; its span says how long it
    # queued behind an earlier judgment and how long its inference took.
    speech.model.hold = HOLD
    speech.speak("a", 0.0, 0.8, "Hey Assistant,")
    speech.speak("b", 1.2, 2.4, "what time is it?")
    await wait_until(lambda: speech.judged("b"), "the second segment was never judged")

    records = speech.runtime.perception.input_trace.snapshot().to_dict()["records"]
    first, second = (r for r in records if r["stage"] == "addressing.semantic")
    trace = speech.runtime.perception.input_trace
    for span, segment_id in ((first, "a"), (second, "b")):
        final = speech.finals[segment_id]
        assert span["observation_id"] == trace.identity(final.observation_id)
        assert span["segment_id"] == trace.identity(segment_id)
        assert span["outcome"] == "done"
        assert span["event_time_ns"] <= span["start_time_ns"]
        assert span["end_time_ns"] - span["start_time_ns"] >= HOLD * 1e9
    # The second queued as its transcript came, behind the first one's inference.
    assert second["event_time_ns"] < first["end_time_ns"] <= second["start_time_ns"]
