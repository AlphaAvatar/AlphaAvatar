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
"""A turn's measurement from what its edges recorded: each output, the request, the bound.

These build the records a turn leaves directly, for cases the chain cannot be steered into
deterministically; ``test_session`` runs the same measurement over the production chain.
"""

from __future__ import annotations

from alphaavatar.host.doctor import samples
from alphaavatar.host.doctor.measure import TurnObservation, scenario
from alphaavatar.host.doctor.transport import LogRecord, OutputRecord

MS = 1_000_000


def identity(value: str) -> str:
    return f"id_{value:>16}"


def trace(at: int, stage: str, sequence: int, **fields: str | int) -> dict:
    hashed = {k: identity(v) if k.endswith("_id") else v for k, v in fields.items()}
    return {"trace_sequence": sequence, "recorded_time_ns": at * MS, "stage": stage, **hashed}


def output(at: int, kind: str, output_id: str | None, **fields: object) -> OutputRecord:
    turn = None if fields.get("control") == "interrupt" else "turn-1"
    return OutputRecord(at * MS, kind, "assistant", turn, "run-1", output_id, **fields)


def observation(records: list[OutputRecord], **extra: object) -> TurnObservation:
    logs = [
        LogRecord(10 * MS, "input.committed", {"session_id": "s", "turn_id": "turn-1"}, "x"),
        LogRecord(
            20 * MS,
            "model.started",
            {"session_id": "s", "turn_id": "turn-1", "run_id": "run-1", "request_id": "req-1"},
        ),
        LogRecord(30 * MS, "model.first_event", {"session_id": "s", "turn_id": "turn-1"}),
        LogRecord(
            60 * MS, "run.finished", {"session_id": "s", "turn_id": "turn-1", "state": "completed"}
        ),
    ]
    records_ = [
        trace(10, "turn.committed", 1, turn_id="turn-1", input_id="input-1"),
        trace(
            21,
            "model.request",
            2,
            turn_id="turn-1",
            run_id="run-1",
            request_id="req-1",
            input_id="input-1",
            frame_count=0,
        ),
        # The typed text itself is in the request.
        trace(
            21,
            "model.request_input",
            3,
            request_id="req-1",
            observation_id="typed-1",
            outcome="carried",
        ),
        *extra.pop("trace", ()),
    ]
    return TurnObservation(
        task=samples.TEXT,
        configuration="original",
        session_id="s",
        start_ns=0,
        timeline=extra.pop("timeline", None),
        turn_id="turn-1",
        records=records,
        logs=logs,
        trace=records_,
        identity=identity,
        audio_output=extra.pop("audio_output", True),
        **extra,
    )


def test_every_output_of_the_run_must_end_normally_before_the_turn_completes() -> None:
    # The review's case: one output completes, the other is interrupted after its first
    # audio frame, later than the first one's completion.
    records = [
        output(40, "text_chunk", "out-a", text="5."),
        output(41, "audio_frame", "out-a", audio_sec=0.02),
        output(42, "control", "out-a", control="text_complete"),
        output(50, "control", "out-a", control="complete"),
        output(45, "text_chunk", "out-b", text=""),
        output(70, "audio_frame", "out-b", audio_sec=0.02),
        output(
            80,
            "control",
            None,
            control="interrupt",
            reason="avatar_directed_barge_in",
            targets=("out-b",),
        ),
    ]
    result = scenario(observation(sorted(records, key=lambda r: r.monotonic_ns)))
    assert (result.outcome, result.blocked_stage) == ("failed", "outputs.complete")
    assert [(o["terminal"], o["reason"]) for o in result.outputs] == [
        ("completed", None),
        ("interrupted", "avatar_directed_barge_in"),
    ]
    metrics = {m.name: m for m in result.metrics}
    # No completion is recorded, so none can precede the interrupted output's last frame.
    assert [
        (metrics[n].value, metrics[n].samples) for n in ("response_final", "audio_last_frame")
    ] == [(None, 0)] * 2
    assert any("interrupted: avatar_directed_barge_in" in line for line in result.details)

    # Both complete: the last completion is the response's, after every frame.
    records[-1] = output(80, "control", "out-b", control="complete")
    result = scenario(observation(sorted(records, key=lambda r: r.monotonic_ns)))
    assert result.outcome == "passed"
    metrics = {m.name: m.value for m in result.metrics}
    assert metrics["audio_last_frame"] == 70 <= metrics["response_final"] == 80

    # Never ended: the turn's own end names how, here a timeout.
    del records[-1]
    result = scenario(observation(sorted(records, key=lambda r: r.monotonic_ns), ended="timeout"))
    assert [o["terminal"] for o in result.outputs] == ["completed", "timed_out"]


def test_a_request_without_the_turns_input_does_not_pass_and_evidence_keeps_its_end() -> None:
    records = [
        output(40, "text_chunk", "out-a", text="5."),
        output(41, "audio_frame", "out-a", audio_sec=0.02),
        output(42, "control", "out-a", control="text_complete"),
        output(50, "control", "out-a", control="complete"),
    ]
    # Many steps on the way: the bound keeps where the chain began, turned and ended.
    noise = [trace(15, "turn.admission", 3 + i, turn_id="turn-1") for i in range(100)]
    result = scenario(observation(records, trace=noise))
    stages = [item.stage for item in result.evidence]
    assert len(stages) == 64
    assert {"turn.committed", "model.request", "model.started", "run.finished"} <= set(stages)

    # The request names another input than the Turn committed: not this Turn's request.
    other = observation(records)
    other.trace[1]["input_id"] = identity("input-2")
    result = scenario(other)
    assert (result.outcome, result.blocked_stage) == ("failed", "request.input")
    assert result.request["carries_turn_input"] is False


def test_frames_context_selected_are_told_apart_from_frames_the_request_carried() -> None:
    from alphaavatar.host.doctor.transport import Frame, SourceTimeline

    timeline = SourceTimeline(started_ns=0, voiced_end_ns=5 * MS, voiced_end_sequence=3)
    timeline.frames = [Frame("screen", n, f"frame-{n}", n * MS, n * MS) for n in (1, 2)]
    steps = [
        trace(15, "context.frame_selected", 3, turn_id="turn-1", observation_id="frame-1"),
        trace(15, "context.frame_selected", 4, turn_id="turn-1", observation_id="frame-2"),
        trace(21, "model.request_frame", 5, request_id="req-1", observation_id="frame-2"),
    ]
    found = observation([], trace=steps, timeline=timeline)
    found.task = samples.VOICE_VISION
    result = scenario(found)
    assert [(f["sequence"], f["selected"], f["requested"]) for f in result.frames] == [
        (1, True, False),
        (2, True, True),
    ]
    assert result.request["sample_frames"] == 1 and "request.frames" in result.reached


def test_a_turn_that_ended_otherwise_keeps_that_end_whatever_completed_after_it() -> None:
    # Every output completes, but inside the trailing window after the turn had ended.
    records = [
        output(40, "text_chunk", "out-a", text="5."),
        output(41, "audio_frame", "out-a", audio_sec=0.02),
        output(42, "control", "out-a", control="text_complete"),
        output(50, "control", "out-a", control="complete"),
    ]
    for ended, outcome in (
        ("timeout", "failed"),
        ("session_failed", "failed"),
        ("interrupted", "interrupted"),
    ):
        result = scenario(observation(list(records), ended=ended))
        assert (result.outcome, result.blocked_stage) == (outcome, f"turn.{ended}")
        metrics = {m.name: m for m in result.metrics}
        for name in ("text_complete", "audio_last_frame", "response_final"):
            assert (metrics[name].value, metrics[name].samples) == (None, 0), (ended, name)
        assert (
            metrics["response_final"].note
            == f"not recorded: the turn ended by {ended.replace('_', ' ')}"
        )
        # What arrived late stays as evidence.
        assert [o["terminal"] for o in result.outputs] == ["completed"]
        assert "output.control" in {item.stage for item in result.evidence}


def test_a_spoken_input_that_never_committed_shows_where_it_stopped() -> None:
    from alphaavatar.host.doctor.transport import SourceTimeline

    # The real chain's case: the segment closed and went to STT, turn-taking held, then
    # cancelled for want of a transcript, and the transcript came after that.
    timeline = SourceTimeline(started_ns=0, voiced_end_ns=5 * MS, voiced_end_sequence=3)
    steps = [
        trace(1, "turn.committed", 1, turn_id="earlier", input_id="input-0"),  # Before: not ours.
        trace(6, "perception.speech_closed", 2, segment_id="seg-1", observation_id="speech-1"),
        trace(6, "stt.commit", 3, segment_id="seg-1", outcome="accepted"),
        trace(7, "candidate.decision", 4, candidate_id="cand-1", decision_id="d-1", action="hold"),
        trace(
            8, "candidate.decision", 5, candidate_id="cand-1", decision_id="d-2", action="cancel"
        ),
        trace(
            9, "stt.terminal", 6, segment_id="seg-1", observation_id="final-1", outcome="final_text"
        ),
    ]
    found = TurnObservation(
        task=samples.VOICE,
        configuration="original",
        session_id="s",
        start_ns=5 * MS,
        timeline=timeline,
        turn_id=None,
        records=[],
        logs=[],
        trace=steps,
        identity=identity,
        audio_output=True,
        ended="timeout",
    )
    result = scenario(found)
    assert result.reached == ("input", "vad.closed", "stt.final")
    assert (result.outcome, result.blocked_stage) == ("failed", "turn.committed")
    decisions = [e.detail["action"] for e in result.evidence if e.stage == "candidate.decision"]
    assert decisions == ["hold", "cancel"]
    assert "turn.committed" not in {e.stage for e in result.evidence}


def test_a_figure_not_measured_carries_why_never_what_it_would_measure() -> None:
    # The model's first event came, then the turn timed out: no text and no speech at all.
    stopped = {m.name: m for m in scenario(observation([], ended="timeout")).segments}
    assert stopped["model_first_text_delta"].value is None
    # What a figure measures is no reason it is missing; where its scenario stopped is.
    assert stopped["model_first_text_delta"].note is None
    assert stopped["tts_request_to_first_pcm"].note is None  # Nor is a TTS never asked.
    # A TTS request and its audio, without the first PCM only HTTP PCM providers log.
    speech = [
        output(40, "text_chunk", "out-a", text="5."),
        output(45, "audio_frame", "out-a", audio_sec=0.02),
        output(50, "control", "out-a", control="complete"),
    ]
    found = observation(speech)
    found.logs.extend(
        (
            LogRecord(35 * MS, "model.first_text", {"session_id": "s", "turn_id": "turn-1"}),
            LogRecord(38 * MS, "speech.segment", {"output_id": "out-a", "segment": 0}),
            LogRecord(
                39 * MS,
                "speech.request",
                {"output_id": "out-a", "segment": 0, "request_id": "tts-1"},
            ),
        )
    )
    spoken = {m.name: m for m in scenario(found).segments}
    assert spoken["tts_request_to_first_pcm"].value is None
    assert spoken["tts_request_to_first_pcm"].note == "this TTS plugin logs no first PCM"
    # A measured figure keeps what describes it.
    assert spoken["model_first_text_delta"].value == 15.0
    assert spoken["model_first_text_delta"].note == "the first token, as far as the stream shows it"


def test_a_session_without_audio_output_says_so_for_each_audio_figure() -> None:
    records = [
        output(40, "text_chunk", "out-a", text="5."),
        output(42, "control", "out-a", control="text_complete"),
        output(50, "control", "out-a", control="complete"),
    ]
    metrics = {m.name: m for m in scenario(observation(records, audio_output=False)).metrics}
    assert metrics["response_final"].value is not None
    for name in ("first_audio_frame", "audio_last_frame"):
        assert (metrics[name].value, metrics[name].note) == (
            None,
            "no audio output in this session",
        )


def spoken(segments: list[tuple[int, int, str | None]], transcript: str, **extra) -> object:
    """The two-sentence question's turn, from its segments: (start ms, end ms, STT outcome),
    its committed transcript and any further trace records; its Turn chains the first."""
    from alphaavatar.host.doctor.transport import SourceTimeline

    records = []
    for index, (start, end, outcome) in enumerate(segments):
        segment = f"seg-{index}"
        records.append(
            trace(end, "perception.speech_closed", 10 * index + 1, segment_id=segment)
            | {"start_time_ns": start * MS, "end_time_ns": end * MS}
        )
        if outcome is not None:
            records.append(
                trace(end + 50, "stt.terminal", 10 * index + 2, segment_id=segment, outcome=outcome)
            )
    # The Turn: its decision joins the first segment's candidate.
    records += [
        trace(4000, "candidate.segment", 90, candidate_id="cand-0", segment_id="seg-0"),
        trace(4001, "candidate.decision", 91, candidate_id="cand-0", decision_id="d-0"),
        trace(4002, "turn.committed", 92, turn_id="turn-1", decision_id="d-0", input_id="input-1"),
        *extra.pop("trace", ()),
    ]
    logs = [
        LogRecord(
            4002 * MS, "input.committed", {"session_id": "s", "turn_id": "turn-1"}, transcript
        )
    ]
    return TurnObservation(
        task=samples.VOICE,
        configuration="original",
        session_id="s",
        start_ns=3140 * MS,
        timeline=SourceTimeline(started_ns=0, voiced_end_ns=3140 * MS),
        turn_id="turn-1",
        records=[],
        logs=logs,
        trace=records,
        identity=identity,
        audio_output=True,
        **extra,
    )


FIRST = "What is two plus three?"


def test_a_sentence_missing_from_the_transcript_is_placed_where_it_was_lost() -> None:
    # The recording's two sentences: about 0.22–1.52 s and 1.76–3.14 s.
    assert samples.speech("sum_question").spans == ((0.22, 1.52), (1.76, 3.14))

    def lost(observation) -> list[tuple[int, str | None, str | None]]:
        found = scenario(observation).sentences
        return [(s["index"], s["lost"], s["why"]) for s in found if not s["heard"]]

    # No segment closed over the second sentence's sound: VAD lost it.
    assert lost(spoken([(200, 1600, "final_text")], FIRST)) == [
        (2, "vad", "no speech segment covered its sound")
    ]
    # One segment held both, and its final the first alone: STT lost it.
    [(index, layer, why)] = lost(spoken([(200, 3200, "final_text")], FIRST))
    assert (index, layer) == (2, "stt") and "holds another sentence and leaves this one out" in why
    # Its own segment closed, and got no final.
    found = spoken([(200, 1600, "final_text"), (1700, 3200, "closed_without_final")], FIRST)
    assert lost(found) == [(2, "stt", "its segment's STT ended closed_without_final")]
    # Its own segment's final came after the Turn committed: the Turn left it out.
    rejected = trace(
        4100, "candidate.transcript_rejected", 95, segment_id="seg-1", reason="retired_segment"
    )
    found = spoken([(200, 1600, "final_text"), (1700, 3200, "final_text")], FIRST, trace=[rejected])
    assert lost(found) == [
        (2, "turn", "its STT final came for a retired segment: the Turn had committed")
    ]
    # Its final came, not rejected, but to another candidate than this Turn's.
    found = spoken([(200, 1600, "final_text"), (1700, 3200, "final_text")], FIRST)
    assert lost(found) == [(2, "turn", "its STT final went to another candidate, not this Turn")]
    # Both heard: nothing lost, each sentence matched to a segment of its own.
    both = spoken([(200, 1600, "final_text"), (1700, 3200, "final_text")], samples.VOICE.prompt)
    found = scenario(both).sentences
    assert [s["heard"] for s in found] == [True, True]
    assert [s["span_ms"] for s in found] == [[220, 1520], [1760, 3140]]
    assert all(s["segment"] and s["stt"] == "final_text" for s in found)


def test_the_95th_percentile_waits_for_enough_samples() -> None:
    from alphaavatar.host.doctor.enums import ScenarioOutcome
    from alphaavatar.host.doctor.measure import P95_SAMPLES, summarize
    from alphaavatar.host.doctor.schemas import Metric, ScenarioResult

    def run(at: int, value: float) -> ScenarioResult:
        metric = Metric("first_text", value, "ms", "a", "b", "c")
        return ScenarioResult(
            "text", ScenarioOutcome.PASSED, "ok", "original", metrics=(metric,), round=at
        )

    few = summarize([run(at, float(at)) for at in range(1, P95_SAMPLES + 1)])[0].figures[0]
    # Round 1 apart: the later rounds are one short of the threshold.
    assert (few.first, few.samples, few.p95) == (1.0, P95_SAMPLES - 1, None)
    many = summarize([run(at, float(at)) for at in range(1, P95_SAMPLES + 2)])[0].figures[0]
    assert (many.samples, many.low, many.high, many.p95) == (P95_SAMPLES, 2.0, 21.0, 20.0)
