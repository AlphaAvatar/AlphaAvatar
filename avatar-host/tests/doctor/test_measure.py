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
"""A turn's measurement from what its edges recorded: each output, the request, the chain.

These build the records a turn leaves directly, on controlled timelines, for cases the chain
cannot be steered into deterministically; ``test_session`` runs the same measurement over the
production chain.
"""

from __future__ import annotations

import pytest

from alphaavatar.host.doctor import samples
from alphaavatar.host.doctor.enums import ScenarioOutcome
from alphaavatar.host.doctor.measure import TurnObservation, scenario, summarize
from alphaavatar.host.doctor.schemas import Metric, ScenarioResult
from alphaavatar.host.doctor.transport import LogRecord, OutputRecord, SourceTimeline

MS = 1_000_000
START = 1000  # The frame with the last voiced sample, in ms


def identity(value: str) -> str:
    return f"id_{value:>16}"


def trace(at: float, stage: str, trace_sequence: int, **fields: str | int) -> dict:
    """A trace record: ``trace_sequence`` is the trace's own order; ``fields`` the record's,
    a ``sequence`` among them (a window's index) another number."""
    hashed = {k: identity(v) if k.endswith("_id") else v for k, v in fields.items()}
    return {
        "trace_sequence": trace_sequence,
        "recorded_time_ns": round(at * MS),
        "stage": stage,
        **hashed,
    }


def log(at: float, name: str, **fields: object) -> LogRecord:
    return LogRecord(round(at * MS), name, {"session_id": "s", **fields})


def output(at: float, kind: str, output_id: str | None, **fields: object) -> OutputRecord:
    turn = None if fields.get("control") == "interrupt" else "turn-1"
    fields.setdefault("request_id", "req-1" if kind == "text_chunk" else None)
    return OutputRecord(round(at * MS), kind, "assistant", turn, "run-1", output_id, **fields)


def answered(text: str = "5.", at: float = 2210, **times: float) -> list[OutputRecord]:
    """One output answering the first request, in text and speech, then completing."""
    audio, done = times.get("audio", 2600), times.get("complete", 3000)
    return [
        output(at, "text_chunk", "out-a", text=text),
        output(audio, "audio_frame", "out-a", audio_sec=0.02),
        output(audio + 10, "control", "out-a", control="text_complete"),
        output(done, "control", "out-a", control="complete"),
    ]


def observation(records: list[OutputRecord] | None = None, **extra: object) -> TurnObservation:
    """The two-sentence question's turn, every node of its chain observed, at round
    milliseconds (``extra`` replaces or adds): one segment, its final carried by the first
    request; that request's text, then its speech."""
    steps = [
        trace(1300, "perception.speech_closed", 1, segment_id="seg-0")
        | {"start_time_ns": 200 * MS, "end_time_ns": 3200 * MS},
        trace(1300, "stt.commit", 2, segment_id="seg-0", outcome="accepted"),
        trace(1500, "stt.terminal", 3, segment_id="seg-0", observation_id="final-0")
        | {"outcome": "final_text", "text_chars": 52},
        trace(1501, "candidate.segment", 4, candidate_id="cand-0", segment_id="seg-0"),
        trace(1502, "candidate.decision", 5, candidate_id="cand-0", decision_id="d-0"),
        trace(1600, "turn.committed", 6, turn_id="turn-1", decision_id="d-0", input_id="input-1"),
        trace(1851, "model.request", 7, turn_id="turn-1", run_id="run-1", request_id="req-1")
        | {"input_id": identity("input-1"), "frame_count": 0},
        trace(1851, "model.request_input", 8, request_id="req-1", observation_id="final-0")
        | {"outcome": "carried"},
        *extra.pop("trace", ()),
    ]
    turn = {"turn_id": "turn-1", "run_id": "run-1"}
    logs = [
        log(1600, "input.committed", turn_id="turn-1"),
        log(1800, "context.ready", turn_id="turn-1", ready=True, wait_ms=180.0),
        log(1850, "context.built", **turn, request_id="req-1"),
        log(1850, "model.started", **turn, request_id="req-1"),
        log(1900, "model.request_sent", request_id="req-1", attempt=1, request_bytes=20_000),
        log(2100, "model.first_event", **turn, request_id="req-1"),
        log(2200, "model.first_text", **turn, request_id="req-1"),
        log(2300, "speech.request", output_id="out-a", segment=0, request_id="tts-1"),
        log(2500, "tts.first_pcm", request_id="tts-1", attempt=1),
        log(3000, "run.finished", **turn, state="completed"),
        *extra.pop("logs", ()),
    ]
    heard = extra.pop("heard", samples.VOICE.prompt)
    logs[0] = LogRecord(logs[0].monotonic_ns, logs[0].name, logs[0].fields, heard)
    return TurnObservation(
        task=extra.pop("task", samples.VOICE),
        configuration="stt scripted",
        session_id="s",
        start_ns=START * MS,
        timeline=extra.pop("timeline", SourceTimeline(started_ns=1, voiced_end_ns=START * MS)),
        turn_id="turn-1",
        records=answered() if records is None else records,
        logs=sorted(logs, key=lambda r: r.monotonic_ns),
        trace=steps,
        identity=identity,
        **extra,
    )


def without(found: TurnObservation, *names: str) -> TurnObservation:
    """The observation without the logs or trace records of these names."""
    found.logs = [r for r in found.logs if r.name not in names]
    found.trace = [r for r in found.trace if r["stage"] not in names]
    return found


def figures(result) -> dict[str, Metric]:
    return {m.name: m for m in (*result.metrics, *result.segments)}


def test_the_stages_add_up_to_the_first_audio_frame_on_one_clock() -> None:
    # Nodes off the millisecond, so each figure is rounded on its own.
    found = observation(answered(at=2210.0004, audio=2600.000_777))
    # Two finals came for the Turn: the request carries the earlier and a later one; a
    # third, later still, it does not carry. Final transcript is the last it carries.
    found.trace += [
        trace(1550.000_31, "stt.terminal", 20, segment_id="seg-1", observation_id="final-1")
        | {"outcome": "final_text"},
        trace(1851, "model.request_input", 21, request_id="req-1", observation_id="final-1")
        | {"outcome": "carried"},
        trace(1590, "stt.terminal", 22, segment_id="seg-2", observation_id="final-2")
        | {"outcome": "final_text"},
        trace(1400.000_1, "perception.speech_closed", 23, segment_id="seg-1")
        | {"start_time_ns": 200 * MS, "end_time_ns": 3200 * MS},
        trace(1555, "candidate.segment", 24, candidate_id="cand-0", segment_id="seg-1"),
        trace(1595, "candidate.segment", 25, candidate_id="cand-0", segment_id="seg-2"),
    ]
    result = scenario(found)
    assert result.outcome == ScenarioOutcome.PASSED
    shown = figures(result)
    # From the raw timestamps: each stage from the node that ends the one before.
    raw = {
        "input": (START * MS, round(1550.000_31 * MS)),
        "context": (round(1550.000_31 * MS), 1900 * MS),
        "output": (1900 * MS, round(2600.000_777 * MS)),
    }
    for stage, (begin, end) in raw.items():
        assert shown[stage].value == round((end - begin) / 1e6, 3), stage
    assert sum(end - begin for begin, end in raw.values()) == round(2600.000_777 * MS) - START * MS
    assert abs(sum(shown[s].value for s in raw) - shown["first_audio_frame"].value) < 0.002
    # Each row from the node before it: VAD close is the last carried final's segment's.
    assert [shown[f"input.{k}"].value for k in ("vad_close", "final_transcript")] == [400, 150]
    assert (shown["context.turn_commit"].start, shown["context.turn_commit"].value) == (
        "Final transcript",
        50.0,
    )
    assert [shown[f"context.{k}"].value for k in ("context_ready", "context_built")] == [200, 50]
    assert shown["context.request_sent"].value == 50
    output_rows = ("first_text_delta", "tts_request", "first_pcm", "first_audio_frame")
    assert [shown[f"output.{k}"].value for k in output_rows] == [300, 100, 200, 100.001]
    assert result.request["finals"] == 2 and result.request["attempts"] == 1


def test_a_node_missing_or_out_of_order_inside_a_stage_is_merged_into_the_next_row() -> None:
    # No first PCM, as a TTS plugin that logs none: the next row runs from the TTS request.
    result = scenario(without(observation(), "tts.first_pcm"))
    shown = figures(result)
    pcm, audio = shown["output.first_pcm"], shown["output.first_audio_frame"]
    assert (pcm.value, pcm.note) == (
        None,
        "merged into the next row: First PCM not observed: this TTS plugin logs no first PCM",
    )
    assert (audio.value, audio.start, audio.merged, audio.samples) == (
        300.0,
        "TTS request",
        ("first_pcm",),
        0,
    )
    assert shown["output"].value == 700  # The stage itself is whole.
    # VAD close recorded before the final speech, as for an earlier segment: out of order.
    early = observation()
    early.trace[0] = early.trace[0] | {"recorded_time_ns": 900 * MS}
    shown = figures(scenario(early))
    assert shown["input.vad_close"].note == "merged into the next row: VAD close came out of order"
    final = shown["input.final_transcript"]
    assert (final.value, final.start, final.merged) == (500.0, "Final speech", ("vad_close",))
    # A merged value is a sample of neither row: the summary leaves it out and counts it.
    rounds = [
        ScenarioResult(
            "voice",
            ScenarioOutcome.PASSED,
            "",
            "c",
            segments=scenario(observation() if at != 2 else early).segments,
            round=at,
        )
        for at in (1, 2, 3)
    ]
    figure = {f.name: f for f in summarize(rounds)[0].figures}["input.final_transcript"]
    assert (figure.first, figure.samples, figure.median, figure.merged) == (200.0, 1, 200.0, 1)


def test_a_stage_missing_a_boundary_is_not_measured_and_says_why() -> None:
    # A provider that logs no request sent: Context and Output have no shared boundary.
    shown = figures(scenario(without(observation(), "model.request_sent")))
    why = "not measured: Model request sent not observed: its provider logs no request sent"
    for name in ("context", "context.request_sent", "output", "output.first_text_delta"):
        assert (shown[name].value, shown[name].note) == (None, why), name
    # The rows inside that do not touch it are still measured, and Input is whole.
    assert shown["context.context_ready"].value == 200 and shown["input"].value == 500
    assert shown["output.tts_request"].value == 100
    # The request carries no final of the sample: Input and Context lose their boundary.
    lost = observation()
    lost.trace = [r for r in lost.trace if r["stage"] != "model.request_input"]
    shown = figures(scenario(lost))
    why = (
        "not measured: Final transcript not observed: the first model request carries no STT final"
    )
    assert (shown["input"].note, shown["context"].note) == (why, why)
    assert shown["input.vad_close"].note.startswith("merged into the next row: VAD close")
    # A loop that logs no Context build: the readiness check runs on to the request sent.
    shown = figures(scenario(without(observation(), "context.built")))
    built, sent = shown["context.context_built"], shown["context.request_sent"]
    assert (
        built.note
        == "merged into the next row: Context built not observed: the loop logs no context built"
    )
    assert (sent.value, sent.start, sent.merged) == (
        100.0,
        "Context readiness check complete",
        ("context_built",),
    )
    # A model that refuses the pictures answers nothing: the rows before First audio frame
    # merge forward, and that last row is not measured, not merged: no round ran from earlier.
    refused = without(observation([]), "model.first_text", "speech.request", "tts.first_pcm")
    segments = scenario(refused).segments
    last = figures(scenario(refused))["output.first_audio_frame"]
    assert (last.value, last.merged) == (None, ())
    assert last.note.startswith("not measured: First audio frame not observed")
    assert figures(scenario(refused))["output"].note == last.note
    failed = [
        ScenarioResult("voice", ScenarioOutcome.FAILED, "", "c", segments=segments, round=at)
        for at in (1, 2)
    ]
    figure = {f.name: f for f in summarize(failed)[0].figures}["output.first_audio_frame"]
    assert (figure.all_samples, figure.merged) == (0, 0)


def test_the_finals_stt_request_is_parted_into_queue_connection_and_exchange() -> None:
    timing = {"outcome": "final", "queue_ms": 1.5, "upload_ms": 4.0, "wait_ms": 90.0}
    timing |= {"first_event_ms": 20.0, "final_ms": 50.0}
    # The Turn's other segment, timed by its own request: not the final's.
    other = log(1200, "stt.request", segment_id="seg-1", reused=False, connect_ms=1.0, **timing)
    opened = log(
        1450,
        "stt.request",
        segment_id="seg-0",
        reused=False,
        connect_ms=40.0,
        tls_ms=60.0,
        **timing,
    )
    joined = trace(1501.5, "candidate.segment", 30, candidate_id="cand-0", segment_id="seg-1")
    shown = figures(scenario(observation(trace=[joined], logs=[other, opened])))
    rows = (
        "stt_queue",
        "stt_connect",
        "stt_tls",
        "stt_upload",
        "stt_wait",
        "stt_first_event",
        "stt_stream",
    )
    assert [shown[name].value for name in rows] == [1.5, 40.0, 60.0, 4.0, 90.0, 20.0, 50.0]
    # A reused connection opens nothing: no connect, no handshake, and says why.
    reused = log(1450, "stt.request", segment_id="seg-0", reused=True, **timing)
    shown = figures(scenario(observation(logs=[reused])))
    assert [(shown[n].value, shown[n].note) for n in ("stt_connect", "stt_tls")] == [
        (None, "none: the connection was reused")
    ] * 2
    assert shown["stt_wait"].value == 90.0
    # A request its transport did not trace: its queue alone, the rest not observed, and
    # neither reused nor without TLS.
    untraced = log(1450, "stt.request", segment_id="seg-0", outcome="final", queue_ms=1.5)
    shown = figures(scenario(observation(logs=[untraced])))
    assert shown["stt_queue"].value == 1.5
    assert {(shown[n].value, shown[n].note) for n in rows[1:]} == {
        (None, "not observed: its transport traced no request")
    }
    # An STT plugin that times nothing: every row says so.
    shown = figures(scenario(observation()))
    assert {shown[n].note for n in rows} == {"not measured: its STT plugin times no request"}


def test_a_speaker_window_and_the_association_carry_when_their_spans_began() -> None:
    # The speaker association a Turn's commit waits for (O-16): each window's queueing and
    # inference, and the association's settling from its speech closed, on the report's clock.
    window = trace(1700, "speaker.window", 30, segment_id="seg-0", sequence=1, outcome="done")
    window |= {"event_time_ns": 1100 * MS, "start_time_ns": 1400 * MS, "end_time_ns": 1700 * MS}
    settled = trace(1720, "speaker.association", 31, segment_id="seg-0", outcome="bound")
    settled |= {"start_time_ns": 1300 * MS, "end_time_ns": 1720 * MS}
    evidence = {e.stage: e for e in scenario(observation(trace=[window, settled])).evidence}
    assert evidence["speaker.window"].detail | {"segment": None} == {
        "sequence": 1,
        "outcome": "done",
        "segment": None,
        "started_ms": 400.0,
        "queued_ms": 100.0,
    }
    assert evidence["speaker.window"].at_ms == 700.0
    assert evidence["speaker.association"].detail["started_ms"] == 300.0
    assert evidence["speaker.association"].at_ms == 720.0


@pytest.mark.parametrize(
    ("ready_at", "asked_at", "values", "wait_note"),
    [
        # Known only after the commit asked: the commit waited for it.
        (1720, 1600, (420.0, 120.0), None),
        # Its subject came with the speech: ready before it closed, no wait needed.
        (
            1200,
            1600,
            (-100.0, 0.2),
            "none needed: every segment of its candidate was ready before the commit asked",
        ),
    ],
)
def test_the_association_ready_and_the_commits_own_wait_are_two_figures(
    ready_at: float, asked_at: float, values: tuple, wait_note: str | None
) -> None:
    settled = trace(1800, "participant.segment_ready", 40, segment_id="seg-0", outcome="bound")
    settled |= {"start_time_ns": 1100 * MS, "end_time_ns": round(ready_at * MS)}
    waited = trace(1801, "candidate.association", 41, candidate_id="cand-0", outcome="ready")
    end = max(ready_at, asked_at + 0.2)
    waited |= {"start_time_ns": asked_at * MS, "end_time_ns": round(end * MS)}
    shown = figures(scenario(observation(trace=[settled, waited])))
    assert (shown["association_ready"].value, shown["association_wait"].value) == values
    assert shown["association_wait"].note == wait_note
    # No resolver recorded one, and the commit waited for none: neither is measured.
    shown = figures(scenario(observation()))
    assert shown["association_ready"].value is shown["association_wait"].value is None
    assert shown["association_ready"].note.startswith("not measured")


def ready_at(at: float, segment: str, trace_sequence: int) -> dict:
    record = trace(at, "participant.segment_ready", trace_sequence, segment_id=segment)
    return record | {"outcome": "bound", "start_time_ns": 1100 * MS, "end_time_ns": at * MS}


def check(asked: float, answered: float, trace_sequence: int, revision: int) -> dict:
    record = trace(answered, "candidate.association", trace_sequence, candidate_id="cand-0")
    record |= {"candidate_revision": revision, "outcome": "ready"}
    return record | {"start_time_ns": asked * MS, "end_time_ns": round(answered * MS)}


def test_the_commits_wait_is_every_check_of_its_candidate_a_re_decisions_too() -> None:
    # Waited for the association, which, once ready, changed the evidence: re-decided and
    # checked again at once. The last check alone would say the commit never waited.
    steps = [ready_at(1720, "seg-0", 40), check(1600, 1720, 41, 1), check(1760, 1760.2, 42, 2)]
    shown = figures(scenario(observation(trace=steps)))["association_wait"]
    assert (shown.value, shown.samples, shown.values) == (120.2, 2, (120.0, 0.2))
    assert shown.note == "2 checks, a re-decision's too, summed"


@pytest.mark.parametrize(
    ("earlier", "answered", "note"),
    [
        (None, 1750, None),  # Never ready: the check timed out on it.
        (1720, 1720, None),  # Ready while the check waited.
        (
            1500,
            1600,
            "none needed: every segment of its candidate was ready before the commit asked",
        ),
    ],
    ids=["never", "during", "before"],
)
def test_no_wait_is_needed_only_when_every_segment_of_the_candidate_was_ready(
    earlier: float | None, answered: float, note: str | None
) -> None:
    # The commit checks each segment of its candidate: its last one, the final's, ready
    # before it asked says nothing of an earlier one.
    joined = trace(1290, "candidate.segment", 38, candidate_id="cand-0", segment_id="seg-a")
    steps = [joined, ready_at(1200, "seg-0", 39), check(1600, answered, 41, 1)]
    if earlier is not None:
        steps.append(ready_at(earlier, "seg-a", 40))
    shown = figures(scenario(observation(trace=steps)))["association_wait"]
    assert (shown.value, shown.note) == (answered - 1600, note)


def span(at: float, stage: str, trace_sequence: int, outcome: str, **times: float) -> dict:
    record = trace(at, stage, trace_sequence, candidate_id="cand-0") | {"outcome": outcome}
    return record | {f"{name}_time_ns": round(value * MS) for name, value in times.items()}


@pytest.mark.parametrize(
    ("assessed", "values", "note"),
    [
        # Replaced as the addressing came, then run again: both in the stretch.
        ([(1500, 1500, 1520, "cancelled"), (1525, 1530, 1590, "done")], 80.0, "2 runs, 1 replaced"),
        ([(1525, 1530, 1590, "failed")], 60.0, "1 run, 1 failed"),
        # Assessed before the final: the commit kept that decision.
        (
            [(1400, 1410, 1470, "done")],
            0.0,
            "none: the commit kept the decision it made before the final",
        ),
    ],
    ids=["replaced", "failed", "before-the-final"],
)
def test_between_the_final_and_the_commit_the_assessments_and_waits_are_figures(
    assessed: list[tuple[float, float, float, str]], values: float, note: str
) -> None:
    # O-16, from the final (1500 ms) to the commit (1600): what the endpoint model ran and the
    # router waited for in that stretch, each span its part within it alone.
    steps = [
        span(1320, "candidate.assessment", 30, "done", event=1300, start=1310, end=1320),
        span(1470, "candidate.hold", 31, "cancelled", start=1320, end=1470),  # Before it
        span(1510, "candidate.addressing_wait", 32, "cancelled", start=1450, end=1510),
        *(
            span(end, "candidate.assessment", 33 + i, outcome, event=queued, start=begun, end=end)
            for i, (queued, begun, end, outcome) in enumerate(assessed)
        ),
        span(1600, "candidate.addressing_wait", 40, "done", start=1590, end=1599.5),
        trace(1600, "candidate.decision", 41, candidate_id="cand-0") | {"action": "commit"},
        span(1700, "candidate.hold", 42, "done", start=1600, end=1700),  # After it: not its
        span(1750, "candidate.assessment", 43, "done", event=1700, start=1710, end=1750),
    ]
    result = scenario(observation(trace=steps))
    shown = figures(result)
    queued, begun = assessed[-1][:2]
    assert shown["assessment_queue"].value == begun - queued
    assessments = shown["endpoint_assessment"]
    assert (assessments.value, assessments.note) == (values, note)
    held = shown["decision_holds"]
    assert (held.value, held.samples, held.values, held.note) == (
        19.5,
        2,
        (10.0, 9.5),
        "addressing_wait",
    )
    queued_at = [
        e.detail["queued_ms"] for e in result.evidence if e.stage == "candidate.assessment"
    ]
    assert queued_at == [300.0, *(q - START for q, *_ in assessed), 700.0]
    # No commit decision: nothing to measure between the final and it.
    uncommitted = [r for r in steps if r["stage"] != "candidate.decision"]
    shown = figures(scenario(observation(trace=uncommitted)))
    assert shown["endpoint_assessment"].value is shown["decision_holds"].value is None


def test_a_retry_is_an_attempt_of_its_own_and_the_first_is_when_the_request_went_out() -> None:
    retry = log(1950, "model.request_sent", request_id="req-1", attempt=2, request_bytes=20_000)
    result = scenario(observation(logs=[retry]))
    shown = figures(result)
    assert shown["context.request_sent"].value == 50  # The first attempt, encoded, sent
    assert shown["output.first_text_delta"].value == 300  # Its wait holds the retry.
    assert result.request["attempts"] == 2 and shown["model_request_attempts"].value == 2
    sent = [e.detail["attempt"] for e in result.evidence if e.stage == "model.request_sent"]
    assert sent == [1, 2]


def test_with_several_requests_in_a_turn_the_first_is_measured_with_its_own_outputs() -> None:
    # The first request calls a tool and says nothing; the second answers, text and speech.
    second = [
        log(2400, "model.started", turn_id="turn-1", run_id="run-1", request_id="req-2"),
        log(2410, "model.request_sent", request_id="req-2", attempt=1),
        log(2450, "model.first_text", turn_id="turn-1", run_id="run-1", request_id="req-2"),
    ]
    found = observation(answered(at=2460), logs=second)
    found.logs = [
        r
        for r in found.logs
        if not (r.name == "model.first_text" and r.fields["request_id"] == "req-1")
    ]
    for record in found.records:
        record.request_id = "req-2" if record.kind == "text_chunk" else None
    found.trace.append(
        trace(2401, "model.request", 30, turn_id="turn-1", run_id="run-1", request_id="req-2")
    )
    result = scenario(found)
    shown = figures(result)
    assert result.request["requests"] == 2
    assert shown["output.first_text_delta"].note == (
        "merged into the next row: First text delta not observed: "
        "the first model request streamed no text"
    )
    assert shown["output"].note == (
        "not measured: First audio frame not observed: "
        "no audio frame answers the first model request"
    )
    assert shown["context"].value == 400  # Up to the first request sent
    assert shown["first_audio_frame"].value == 1600  # End to end, whichever request it answers


def test_every_output_of_the_run_must_end_normally_before_the_turn_completes() -> None:
    # One output completes; the other is interrupted after its first audio frame, later
    # than the first one's completion.
    records = [
        *answered(),
        output(2450, "text_chunk", "out-b", text=""),
        output(3070, "audio_frame", "out-b", audio_sec=0.02),
        output(
            3080,
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
    records[-1] = output(3100, "control", "out-b", control="complete")
    result = scenario(observation(sorted(records, key=lambda r: r.monotonic_ns)))
    assert result.outcome == "passed"
    metrics = {m.name: m.value for m in result.metrics}
    assert metrics["audio_last_frame"] == 2070 <= metrics["response_final"] == 2100

    # Never ended: the turn's own end names how, here a timeout.
    del records[-1]
    result = scenario(observation(sorted(records, key=lambda r: r.monotonic_ns), ended="timeout"))
    assert [o["terminal"] for o in result.outputs] == ["completed", "timed_out"]


def test_a_request_without_the_turns_input_does_not_pass_and_evidence_keeps_its_end() -> None:
    # Many steps on the way: the bound keeps where the chain began, turned and ended.
    noise = [trace(1550, "turn.admission", 100 + i, turn_id="turn-1") for i in range(100)]
    result = scenario(observation(trace=noise))
    stages = [item.stage for item in result.evidence]
    assert len(stages) == 64
    assert {"turn.committed", "model.request", "model.started", "run.finished"} <= set(stages)

    # The request names another input than the Turn committed: not this Turn's request.
    other = observation()
    other.trace[6]["input_id"] = identity("input-2")
    result = scenario(other)
    assert (result.outcome, result.blocked_stage) == ("failed", "request.input")
    assert result.request["carries_turn_input"] is False


def test_frames_context_selected_are_told_apart_from_frames_the_request_carried() -> None:
    from alphaavatar.host.doctor.transport import Frame

    timeline = SourceTimeline(started_ns=1, voiced_end_ns=START * MS, voiced_end_sequence=3)
    timeline.frames = [Frame("screen", n, f"frame-{n}", n * MS, n * MS) for n in (1, 2)]
    steps = [
        trace(1700, "context.frame_selected", 30, turn_id="turn-1", observation_id="frame-1"),
        trace(1700, "context.frame_selected", 31, turn_id="turn-1", observation_id="frame-2"),
        trace(1851, "model.request_frame", 32, request_id="req-1", observation_id="frame-2"),
    ]
    found = observation(trace=steps, timeline=timeline, task=samples.VOICE_VISION)
    result = scenario(found)
    assert [(f["sequence"], f["selected"], f["requested"]) for f in result.frames] == [
        (1, True, False),
        (2, True, True),
    ]
    assert result.request["sample_frames"] == 1 and "request.frames" in result.reached


def test_a_turn_that_ended_otherwise_keeps_that_end_whatever_completed_after_it() -> None:
    # Every output completes, but inside the trailing window after the turn had ended.
    for ended, outcome in (
        ("timeout", "failed"),
        ("session_failed", "failed"),
        ("interrupted", "interrupted"),
    ):
        result = scenario(observation(ended=ended))
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


def test_a_spoken_input_that_never_committed_shows_where_it_stopped() -> None:
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
        configuration="c",
        session_id="s",
        start_ns=5 * MS,
        timeline=timeline,
        turn_id=None,
        records=[],
        logs=[],
        trace=steps,
        identity=identity,
        ended="timeout",
    )
    result = scenario(found)
    assert result.reached == ("input", "vad.closed", "stt.final")
    assert (result.outcome, result.blocked_stage) == ("failed", "turn.committed")
    decisions = [e.detail["action"] for e in result.evidence if e.stage == "candidate.decision"]
    assert decisions == ["hold", "cancel"]
    assert "turn.committed" not in {e.stage for e in result.evidence}


def spoken(segments: list[tuple[int, int, str | None]], heard: str, **extra) -> TurnObservation:
    """The two-sentence question's turn, from its segments: (start ms, end ms, STT outcome).
    Each final comes 50 ms after its segment closes; the Turn takes the first segment, its
    final and any of ``taken``, and commits at 4002 ms."""
    taken = extra.pop("taken", ())
    records = []
    for index, (start, end, outcome) in enumerate(segments):
        segment = f"seg-{index}"
        records.append(
            trace(end, "perception.speech_closed", 10 * index + 1, segment_id=segment)
            | {"start_time_ns": start * MS, "end_time_ns": end * MS}
        )
        if outcome is not None:
            final = trace(end + 50, "stt.terminal", 10 * index + 2, segment_id=segment)
            final |= {"outcome": outcome, "observation_id": identity(f"final-{index}")}
            records.append(final | {"text_chars": 23})
    records += [
        trace(4000, "candidate.segment", 90, candidate_id="cand-0", segment_id="seg-0"),
        trace(4001, "candidate.decision", 91, candidate_id="cand-0", decision_id="d-0"),
        trace(4002, "turn.committed", 92, turn_id="turn-1", decision_id="d-0", input_id="input-1"),
        trace(4003, "model.request", 93, turn_id="turn-1", run_id="run-1", request_id="req-1"),
        *(
            trace(4003, "model.request_input", 94, request_id="req-1", observation_id=f"final-{i}")
            | {"outcome": "carried"}
            for i in (0, *taken)
        ),
        *extra.pop("trace", ()),
    ]
    logs = [
        LogRecord(4002 * MS, "input.committed", {"session_id": "s", "turn_id": "turn-1"}, heard),
        log(4003, "model.started", turn_id="turn-1", run_id="run-1", request_id="req-1"),
    ]
    return TurnObservation(
        task=samples.VOICE,
        configuration="c",
        session_id="s",
        start_ns=3140 * MS,
        timeline=SourceTimeline(started_ns=1, voiced_end_ns=3140 * MS),
        turn_id="turn-1",
        records=[],
        logs=logs,
        trace=records,
        identity=identity,
        **extra,
    )


FIRST = "What is two plus three?"


def lost(found: TurnObservation) -> list[tuple[int, str | None, str | None]]:
    sentences = scenario(found).sentences
    return [(s["index"], s["lost"], s["why"]) for s in sentences if not s["heard"]]


def test_a_sentence_missing_from_the_transcript_is_placed_where_it_was_lost() -> None:
    # The recording's two sentences: about 0.22–1.52 s and 1.76–3.14 s.
    assert samples.speech("sum_question").spans == ((0.22, 1.52), (1.76, 3.14))
    # Both heard, a segment each: the two-sentence regression's passing case.
    found = scenario(
        spoken(
            [(200, 1600, "final_text"), (1700, 3200, "final_text")],
            samples.VOICE.prompt,
            taken=(1,),
        )
    ).sentences
    assert [(s["heard"], s["coverage"], s["stt"], s["adopted"]) for s in found] == [
        (True, "full", "final", True)
    ] * 2
    assert [s["content"] for s in found] == ["holds_its_words"] * 2

    # No segment closed over the second sentence's sound: VAD lost it.
    assert lost(spoken([(200, 1600, "final_text")], FIRST)) == [
        (2, "vad", "no speech segment covered its sound")
    ]
    # A segment over only part of it: VAD cut it short.
    [(index, layer, why)] = lost(
        spoken([(200, 1600, "final_text"), (1700, 2500, "final_text")], FIRST, taken=(1,))
    )
    assert (index, layer) == (2, "vad") and why.startswith("speech segments held 740 ms")
    # One segment held both, and the final the Turn took left the second out: STT.
    [(index, layer, why)] = lost(spoken([(200, 3200, "final_text")], FIRST))
    assert (index, layer) == (2, "stt") and "holds another sentence too" in why
    # Several segments over it, none of them with a final.
    found = spoken(
        [
            (200, 1600, "final_text"),
            (1700, 2400, "closed_without_final"),
            (2400, 3200, "final_empty"),
        ],
        FIRST,
    )
    assert lost(found) == [
        (2, "stt", "no STT final for its segment: closed_without_final, final_empty")
    ]
    # Its own segment's final came after the Turn committed, for a segment it had retired.
    rejected = trace(4100, "candidate.transcript_rejected", 95, segment_id="seg-1")
    found = spoken(
        [(200, 1600, "final_text"), (1700, 3200, "final_text")],
        FIRST,
        trace=[rejected | {"reason": "retired_segment"}],
    )
    assert lost(found)[0][1] == "turn"
    assert scenario(found).sentences[1]["stt"] == "late"
    # Its final came in time, but the Turn did not take it.
    found = spoken([(200, 1600, "final_text"), (1700, 3200, "final_text")], FIRST)
    assert lost(found) == [(2, "turn", "its STT final came in time, but the Turn did not take it")]
    # The Turn took it, and it lacks the words: what STT heard, not where the sound went.
    [(index, layer, why)] = lost(
        spoken([(200, 1600, "final_text"), (1700, 3200, "final_text")], FIRST, taken=(1,))
    )
    assert (layer, why) == ("stt", "the final the Turn took (23 characters) lacks its words")


def test_where_the_evidence_cannot_place_a_sentence_it_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The recording's stretches no longer match its sentences: their sound cannot be placed.
    monkeypatch.setattr(samples, "speech", lambda name: samples.Speech(name, bytes(32_000), 1.0))
    found = scenario(spoken([(200, 3200, "final_text")], FIRST)).sentences
    assert [(s["coverage"], s["covered_ms"], s["lost"]) for s in found if not s["heard"]] == [
        (None, None, "unknown")
    ]


def test_a_figure_not_measured_carries_why_never_what_it_would_measure() -> None:
    # The model's first event came, then the turn timed out: no text and no speech at all.
    stopped = observation([], ended="timeout")
    stopped = figures(
        scenario(without(stopped, "model.first_text", "speech.request", "tts.first_pcm"))
    )
    delta = stopped["output.first_text_delta"]
    assert delta.note == (
        "merged into the next row: First text delta not observed: "
        "the first model request streamed no text"
    )
    assert stopped["output"].note == (
        "not measured: First audio frame not observed: "
        "no audio frame answers the first model request"
    )
    # A measured figure keeps what describes it.
    shown = figures(scenario(observation()))
    assert shown["context_ready_wait"].note == "how long registered context work held it back"
    assert shown["model_first_event"].value == 200


def run(at: int, value: float | None, outcome: str = "passed", **fields) -> ScenarioResult:
    metric = Metric("first_text", value, "ms", "a", "b", "c", note=None if value else "why")
    return ScenarioResult(
        "voice", ScenarioOutcome(outcome), "", "c", metrics=(metric,), round=at, **fields
    )


def test_the_95th_percentile_waits_for_enough_samples() -> None:
    from alphaavatar.host.doctor.measure import P95_SAMPLES

    few = summarize([run(at, float(at)) for at in range(1, P95_SAMPLES + 1)])[0].figures[0]
    # Round 1 apart: the later rounds are one short of the threshold.
    assert (few.first, few.samples, few.p95) == (1.0, P95_SAMPLES - 1, None)
    many = summarize([run(at, float(at)) for at in range(1, P95_SAMPLES + 2)])[0].figures[0]
    assert (many.samples, many.low, many.high, many.p95) == (P95_SAMPLES, 2.0, 21.0, 20.0)


def test_the_summary_keeps_passed_rounds_apart_from_every_round_observed() -> None:
    # Every round failed: nothing passed, every value observed still counted apart.
    failed = summarize([run(at, 100.0 * at, "failed") for at in (1, 2, 3)])[0]
    figure = failed.figures[0]
    assert (failed.passed, figure.first, figure.samples, figure.median) == (0, None, 0, None)
    assert (figure.all_first, figure.all_samples, figure.all_median) == (100.0, 2, 250.0)
    assert (figure.all_low, figure.all_high) == (200.0, 300.0)
    # The first round failed: no Round 1 value; the later passed ones are the samples.
    first = summarize([run(1, 50.0, "failed"), run(2, 20.0), run(3, 40.0)])[0].figures[0]
    assert (first.first, first.samples, first.median, first.all_first) == (None, 2, 30.0, 50.0)
    # A value missing in some rounds: n counts the rounds that observed it.
    partial = summarize([run(1, 10.0), run(2, None), run(3, 30.0), run(4, 50.0)])[0].figures[0]
    assert (partial.samples, partial.median, partial.note) == (2, 40.0, None)
    # Observed in no round: no value anywhere, and why.
    none = summarize([run(1, None), run(2, None, "failed")])[0]
    assert (none.figures[0].all_samples, none.figures[0].note, none.stopped_at) == (
        0,
        "why",
        {"failed": 1},
    )
    assert summarize([run(1, 1.0, sample="sum_question sha256:abc")])[0].sample == (
        "sum_question sha256:abc"
    )
