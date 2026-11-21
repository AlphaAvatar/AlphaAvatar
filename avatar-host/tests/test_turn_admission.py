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
"""Turn admission, on the configured chain: a commit decision the Engine cannot admit closes its
input and leaves no Turn, and the input trace says why. A stale decision is ignored; one whose
evidence is lost or says nothing is rejected, and the trace is frozen for it. Speech that went
untranscribed is admitted on its notices alone, and only while it can still be answered. A new
Turn stops the answer still under way, as does an interrupt, unless its input was committed."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

import pytest
from configured_chain import DEVICE, Chain, configured_chain, wait_until

from alphaavatar.agents.router.enums import InteractionEntityKind, TurnTakingAction, TurnTakingMode
from alphaavatar.agents.router.schemas import InteractionEntityRef, TurnTakingDecision
from alphaavatar.core.env import EnvObservation, EnvOutput
from alphaavatar.core.env.enums import ObservationKind, SpeechCancellationReason
from alphaavatar.core.env.schemas import PerceptionSegmentRef, PerceptionSourceRef
from alphaavatar.core.media import AudioFrame, AudioFramePayload, TextPayload
from alphaavatar.core.output.enums import OutputControlType, OutputKind
from alphaavatar.core.turn.enums import TurnInputModality
from alphaavatar.core.turn.schemas import TurnNotice

AVATAR = (InteractionEntityRef(InteractionEntityKind.AVATAR),)
UNAVAILABLE = TurnNotice("voice.transcription_unavailable", ("segment-1",))
UNCERTAIN = TurnNotice("router.addressing_uncertain")
# Uncertainty about its segment, not of its transcript.
UNSURE = TurnNotice("router.speech_completion_uncertain", ("segment-1",))
SPEECH, TRANSCRIPT = ObservationKind.SPEECH_SEGMENT, ObservationKind.TRANSCRIPT_SEGMENT


Heard = dict[ObservationKind, str]


@pytest.fixture
async def session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owned_addresses: set[object]
) -> AsyncIterator[tuple[Chain, Heard]]:
    """A session that has answered one utterance, segment-1, and that Turn's inputs by kind: its
    speech and its transcript, what the decisions below propose again as another input."""
    async with configured_chain(
        tmp_path, monkeypatch, owned_addresses, ((0.3, "What is two plus three?"),)
    ) as chain:
        chain.say("segment-1")
        await wait_until(lambda: chain.completed() == 1, "the first turn never completed")
        turn = chain.execution.runtime.turn.latest
        yield (
            chain,
            {
                event.observation.kind: event.observation.observation_id
                for event in turn.perception_events
                if event.observation is not None
                and event.observation.observation_id in turn.input_observation_ids
            },
        )


def admissions(chain: Chain, input_id: str = "input-2") -> list[dict]:
    """The Engine's trace of each admission of the input."""
    identity = chain.execution.runtime.perception.input_trace.identity(input_id)
    return [r for r in chain.records("turn.admission") if r["input_id"] == identity]


def propose(
    chain: Chain,
    heard: Heard,
    inputs: tuple[str, ...],
    notices: tuple[TurnNotice, ...] = (),
    addressees: tuple[InteractionEntityRef, ...] = AVATAR,
    input_id: str = "input-2",
    mode: TurnTakingMode = TurnTakingMode.AUDIO_ONLY,
    action: TurnTakingAction = TurnTakingAction.COMMIT,
    reason: str | None = None,
    **data: object,
) -> None:
    """Publish a decision as turn taking does, with ``data`` over its context and its deadline,
    10 s ahead."""
    runtime = chain.execution.runtime
    decision = TurnTakingDecision(
        input_id=input_id,
        revision=1,
        turn_mode=mode,
        action=action,
        confidence=1.0,
        addressees=addressees,
        input_observation_ids=inputs,
        system_notices=notices,
        reason=reason,
    )
    annotation = decision.to_annotation(source="test.turn_taking", observation_id=heard[SPEECH])
    deadline = runtime.clock.now().monotonic_ns + 10_000_000_000
    annotation = replace(
        annotation,
        data={
            **annotation.data,
            "context_id": runtime.state.context_id,
            "admission_deadline_ns": deadline,
            **data,
        },
    )
    assert runtime.perception.publish_annotation(annotation) is not None


async def decide(
    chain: Chain, heard: Heard, *args: object, input_id: str = "input-2", **data: object
) -> dict:
    """Propose, and return the Engine's trace of its admission."""
    before = len(admissions(chain, input_id))
    propose(chain, heard, *args, input_id=input_id, **data)
    await wait_until(
        lambda: len(admissions(chain, input_id)) > before, "the decision was never admitted"
    )
    return admissions(chain, input_id)[-1]


def frozen(chain: Chain) -> list[str]:
    return [
        item.reason for item in chain.execution.runtime.perception.input_trace.snapshot().frozen
    ]


async def type_message(chain: Chain) -> None:
    """A message typed after the utterance, a Turn of its own."""
    runtime = chain.execution.runtime
    await chain.execution.engine.submit_input(
        EnvObservation.text_input(
            time_range=runtime.clock.point(),
            source=PerceptionSourceRef("keyboard", 1),
            device_id=DEVICE,
            payload=TextPayload.create(text="And four plus four?"),
        )
    )
    assert runtime.turn.latest.metadata.get("source") == "avatar.engine.direct"


async def end_speech_source(chain: Chain) -> None:
    runtime = chain.execution.runtime
    runtime.perception.publish_observation(
        EnvObservation.speech_cancelled(
            reason=SpeechCancellationReason.SOURCE_ENDED,
            time_range=runtime.clock.point(),
            source=chain.speech,
            segment=PerceptionSegmentRef(chain.speech, "segment-x"),
            device_id=DEVICE,
        )
    )
    assert not runtime.perception.speech_source_is_current(chain.speech)


async def start_speaking(chain: Chain) -> None:
    """Someone starts speaking, and has not finished."""
    runtime = chain.execution.runtime
    runtime.perception.publish_observation(
        EnvObservation.speech_frame(
            time_range=runtime.clock.point(),
            source=chain.speech,
            segment=PerceptionSegmentRef(chain.speech, "segment-2"),
            device_id=DEVICE,
            payload=AudioFramePayload.create(
                frame=AudioFrame(16_000, 1, 160, bytes(320)), frame_id=None
            ),
            metadata={"speech_event": "start", "route_index": 1},
        )
    )
    assert runtime.perception.has_active_speech


async def mute(chain: Chain) -> None:
    interaction = chain.execution.runtime.state.interaction_method
    interaction.text_output = interaction.audio_output = False


async def leave_source(chain: Chain) -> None:
    chain.execution.runtime.participants.retire_source(chain.speech)


Before = Callable[[Chain], Awaitable[None]] | None

# Each: what happens before the decision, and the annotation data it carries.
STALE: dict[str, tuple[Before, dict[str, object]]] = {
    "admission_expired": (None, {"admission_deadline_ns": 1}),
    "admission_deadline_invalid": (None, {"admission_deadline_ns": "soon"}),
    "context_changed": (None, {"context_id": "another-context"}),
    "speech_source_retired": (end_speech_source, {}),
    "superseded": (type_message, {}),  # Its speech began before a later Turn committed.
}


@pytest.mark.parametrize("reason", STALE)
async def test_a_stale_decision_is_ignored_and_closes_its_input(
    session: tuple[Chain, Heard], reason: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="alphaavatar.agents")
    (chain, heard), (before, data) = session, STALE[reason]
    if before is not None:
        await before(chain)
    runtime, proposed = chain.execution.runtime, (heard[SPEECH], heard[TRANSCRIPT])
    latest = runtime.turn.latest

    found = await decide(chain, heard, proposed, **data)
    assert (found["outcome"], found["reason"]) == ("ignored", reason)
    assert (found["evidence_count"], found["missing_count"]) == (0, 0)
    assert runtime.turn.latest is latest and reason not in frozen(chain)
    assert not any(line.startswith("Skipped superseded") for line in caplog.messages)
    # The input is closed: proposing it again finds it so.
    again = await decide(chain, heard, proposed)
    assert (again["outcome"], again["reason"]) == ("ignored", "input_terminal")
    assert runtime.turn.latest is latest


async def test_a_decision_a_later_turn_was_cut_off_after_is_skipped_as_committed(
    session: tuple[Chain, Heard], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="alphaavatar.agents")
    chain, heard = session
    # A message is typed before the Engine reads the decision: its Turn commits first, and its
    # cutoff covers the decision.
    propose(chain, heard, (heard[SPEECH], heard[TRANSCRIPT]))
    await type_message(chain)
    latest = chain.execution.runtime.turn.latest
    await wait_until(lambda: admissions(chain), "the decision was never admitted")

    (found,) = admissions(chain)
    assert (found["outcome"], found["reason"]) == ("ignored", "superseded")
    assert found["sequence"] <= latest.cutoff.sequence
    assert "Skipped superseded turn decision input_id=input-2" in caplog.messages
    again = await decide(chain, heard, (heard[SPEECH], heard[TRANSCRIPT]))
    assert (again["outcome"], again["reason"]) == ("ignored", "input_terminal")
    assert chain.execution.runtime.turn.latest is latest


@pytest.mark.parametrize(
    ("mode", "modality"),
    [
        (TurnTakingMode.AUDIO_ONLY, TurnInputModality.AUDIO),
        (TurnTakingMode.VISUAL_ONLY, TurnInputModality.IMAGE),
        (TurnTakingMode.AUDIO_VISUAL, TurnInputModality.MULTIMODAL),
    ],
)
async def test_a_decision_with_words_is_admitted_as_its_mode_heard_it(
    session: tuple[Chain, Heard], mode: TurnTakingMode, modality: TurnInputModality
) -> None:
    chain, heard = session
    found = await decide(chain, heard, (heard[TRANSCRIPT], heard[SPEECH]), mode=mode)
    assert (found["outcome"], found["reason"], found["evidence_count"]) == (
        "accepted",
        "committed",
        2,
    )
    turn = chain.execution.runtime.turn.latest
    assert (turn.input_id, turn.modality) == ("input-2", modality)
    assert turn.text == "What is two plus three?" and turn.system_notices == ()


async def test_a_committed_input_is_never_admitted_again(session: tuple[Chain, Heard]) -> None:
    chain, heard = session
    latest = chain.execution.runtime.turn.latest
    proposed = (heard[SPEECH], heard[TRANSCRIPT])
    found = await decide(chain, heard, proposed, input_id=latest.input_id)
    assert (found["outcome"], found["reason"]) == ("ignored", "input_terminal")
    assert chain.execution.runtime.turn.latest is latest


# Each: the decision's inputs (an observation by kind, or one that is gone) and its notices; the
# reason of its rejection, and how many inputs it proposed and how many of them were gone.
REJECTED = {
    "evidence lost": ((TRANSCRIPT, "gone"), (), "evidence_unavailable", 2, 1),
    "no evidence": ((), (), "evidence_unavailable", 0, 0),
    "speech alone": ((SPEECH,), (), "no_usable_input", 1, 0),
    "only uncertainty": ((SPEECH,), (UNSURE,), "no_usable_input", 1, 0),
    "a notice of no segment": ((SPEECH,), (TurnNotice("voice.noise"),), "no_usable_input", 1, 0),
    "a notice of another segment": (
        (SPEECH,),
        (TurnNotice("voice.transcription_unavailable", ("segment-9",)),),
        "no_usable_input",
        1,
        0,
    ),
}


@pytest.mark.parametrize("case", REJECTED)
async def test_a_decision_without_usable_evidence_is_rejected_and_freezes_the_trace(
    session: tuple[Chain, Heard], case: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="alphaavatar.agents")
    (chain, heard), (kinds, notices, reason, evidence, missing) = session, REJECTED[case]
    latest = chain.execution.runtime.turn.latest

    found = await decide(chain, heard, tuple(heard.get(kind, kind) for kind in kinds), notices)
    assert (found["outcome"], found["reason"]) == ("rejected", reason)
    assert (found["evidence_count"], found["missing_count"]) == (evidence, missing)
    assert chain.execution.runtime.turn.latest is latest and frozen(chain)[-1] == reason
    (line,) = [
        r.getMessage() for r in caplog.records if "Turn admission rejected" in r.getMessage()
    ]
    assert line.startswith(f"Turn admission rejected input_id=input-2 reason={reason}")
    if reason == "evidence_unavailable":
        assert line.endswith(f" evidence_count={evidence} missing_count={missing}")

    again = await decide(chain, heard, (heard[SPEECH], heard[TRANSCRIPT]))
    assert (again["outcome"], again["reason"]) == ("ignored", "input_terminal")


# Each: what happens before the decision, its notices and addressees; whether it is admitted.
UNTRANSCRIBED: dict[str, tuple[Before, tuple[TurnNotice, ...], tuple, bool]] = {
    "for the Avatar": (None, (UNAVAILABLE,), AVATAR, True),
    "perhaps for the Avatar": (None, (UNAVAILABLE, UNCERTAIN), (), True),
    "another notice of its segment": (
        None,
        (TurnNotice("voice.cut", ("segment-1",)),),
        AVATAR,
        True,
    ),
    "a notice of no segment": (
        None,
        (TurnNotice("voice.transcription_unavailable"),),
        AVATAR,
        True,
    ),
    "for someone else": (None, (UNAVAILABLE,), (), False),
    "while someone speaks": (start_speaking, (UNAVAILABLE,), AVATAR, False),
    "with no way to answer": (mute, (UNAVAILABLE,), AVATAR, False),
    "from a source the participants left": (leave_source, (UNAVAILABLE,), AVATAR, False),
}


@pytest.mark.parametrize("case", UNTRANSCRIBED)
async def test_untranscribed_speech_is_admitted_on_its_notices_only_while_it_can_be_answered(
    session: tuple[Chain, Heard], case: str
) -> None:
    (chain, heard), (before, notices, addressees, admitted) = session, UNTRANSCRIBED[case]
    if before is not None:
        await before(chain)
    runtime = chain.execution.runtime
    latest = runtime.turn.latest

    found = await decide(chain, heard, (heard[SPEECH],), notices, addressees)
    if not admitted:
        assert (found["outcome"], found["reason"]) == ("ignored", "notice_superseded")
        assert runtime.turn.latest is latest
        return
    assert (found["outcome"], found["reason"], found["evidence_count"]) == (
        "accepted",
        "system_notice",
        1,
    )
    turn = runtime.turn.latest
    assert turn.input_id == "input-2" and turn.modality == TurnInputModality.SYSTEM
    assert turn.system_notices == notices and turn.text is None


@asynccontextmanager
async def outputs(chain: Chain) -> AsyncIterator[list[EnvOutput]]:
    """Every output from now on, as it goes out."""
    stream = chain.execution.runtime.output.stream
    subscription = await stream.subscribe("test.admission.outputs", max_pending=4096)
    seen: list[EnvOutput] = []

    async def collect() -> None:
        while True:
            seen.append((await subscription.get()).output)

    task = asyncio.create_task(collect())
    try:
        yield seen
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await stream.unsubscribe("test.admission.outputs")


def answering(seen: list[EnvOutput], turn_id: str) -> bool:
    return any(
        output.kind != OutputKind.CONTROL and output.scope and output.scope.turn_id == turn_id
        for output in seen
    )


def stopped(seen: list[EnvOutput], reason: str) -> set[str]:
    """The Turns whose answer was interrupted for the reason."""
    return {
        target.scope.turn_id
        for output in seen
        if output.kind == OutputKind.CONTROL
        and output.payload.type == OutputControlType.INTERRUPT
        and output.payload.reason == reason
        for target in output.payload.targets
    }


async def test_a_new_turn_stops_the_answer_still_under_way(session: tuple[Chain, Heard]) -> None:
    chain, _ = session
    async with outputs(chain) as seen:
        await type_message(chain)
        first = chain.execution.runtime.turn.latest
        await wait_until(lambda: answering(seen, first.turn_id), "the first answer never began")
        await type_message(chain)
        await wait_until(
            lambda: first.turn_id in stopped(seen, "superseded"), "the first answer went on"
        )


async def test_an_interrupt_stops_the_answer_unless_its_input_was_committed(
    session: tuple[Chain, Heard],
) -> None:
    chain, heard = session
    proposed = (heard[SPEECH], heard[TRANSCRIPT])
    async with outputs(chain) as seen:
        # input-2 is covered by the typed Turn, so closed as committed; input-3 is refused.
        propose(chain, heard, proposed)
        await type_message(chain)
        answer = chain.execution.runtime.turn.latest
        await wait_until(lambda: admissions(chain), "input-2 was never admitted")
        await decide(chain, heard, proposed, input_id="input-3", admission_deadline_ns=1)
        await wait_until(lambda: answering(seen, answer.turn_id), "the answer never began")

        # Decisions are read in order: once input-3's interrupt is through, input-2's was too.
        interrupt = TurnTakingAction.INTERRUPT
        propose(chain, heard, (), action=interrupt, reason="input_2_spoke")
        propose(chain, heard, (), input_id="input-3", action=interrupt, reason="input_3_spoke")
        await wait_until(
            lambda: answer.turn_id in stopped(seen, "input_3_spoke"), "the answer went on"
        )
        assert not stopped(seen, "input_2_spoke")
