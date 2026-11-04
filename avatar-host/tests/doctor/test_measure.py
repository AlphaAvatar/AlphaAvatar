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
        audio_output=True,
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
