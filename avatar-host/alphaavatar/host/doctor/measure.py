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
"""One diagnostic turn, from what its edges observed, as a scenario result.

Evidence joins by identity. The session names the Turn its own input started; the input
trace hashes identities per session, so that Turn's records are found through
``InputTrace.identity`` and the decision, candidate, segment and request identities they
share. The Turn's first model request is the one measured: its records name the committed
input, which of the Turn's input observations it carries (the STT finals of the sample's
speech among them) and the frames it carries, matched to the ones Doctor published and told
apart from the ones Context selected; its outputs are the ones whose text it streamed. Each
output of the Turn's run ends normally, by failure, by interruption or not at all. A turn that
ended otherwise (a timeout, an interruption, a failed session) keeps that end, whatever
arrived after it; only a turn that completed has completion times. Every time is
``time.monotonic_ns``; intervals are milliseconds from the frame carrying the last voiced
sample.

From that frame to the first audio frame, the chain (``NODES``) parts into three stages,
Input, Context and Output, each starting at the node that ends the one before: for a round
with every boundary, the stages add up to the first audio frame exactly. A node inside a stage
that is missing, or came out of order, is merged: the next interval runs from the last node
observed in order, and is no sample of its row. A stage missing a boundary is not measured,
and says why. RTC transport and client playback come after the output boundary, apart.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import samples
from .enums import ScenarioOutcome
from .samples import Task
from .schemas import Evidence, FigureSummary, Metric, ScenarioResult, ScenarioSummary
from .transport import LogRecord, OutputRecord, SourceTimeline

_EXCERPT = 200
_EVIDENCE = 64
_ASSISTANT = "assistant"
_CONTENT = ("text_chunk", "audio_frame")
# Kept when evidence is cut to its bound: where the chain began, turned and ended.
_TERMINAL = frozenset(
    (
        "input.voiced_end",
        "perception.speech_closed",
        "stt.terminal",
        "turn.committed",
        "context.visual",
        "model.request",
        "model.started",
        "model.request_sent",
        "run.finished",
        "output.control",
        "output.audio_frame_last",
    )
)
_UNFINISHED = {"timeout": "timed_out", "interrupted": "interrupted"}
# Where a sentence that is not in the transcript was lost, as the stage the scenario stopped at.
_LOST_AT = {"vad": "vad.closed", "stt": "stt.final", "turn": "turn.committed"}
_COVERED = 0.95  # Of a sentence's sound in speech segments: less leaves part of it out.
# Why Doctor ends the outputs of a turn that did not end on its own.
TURN_ENDED = "doctor_turn_ended"
# The chain from the last voiced sample to the first audio frame, in the order a turn passes
# it, and its stages: each from its first node to its last, the first shared with the stage
# before. A row is named by its stage and the node it ends at.
NODES = (
    ("speech_end", "Final speech"),
    ("vad_close", "VAD close"),
    ("final_transcript", "Final transcript"),
    ("turn_commit", "Turn commit"),
    ("context_ready", "Context readiness check complete"),
    ("context_built", "Context built"),
    ("request_sent", "Model request sent"),
    ("first_text_delta", "First text delta"),
    ("tts_request", "TTS request"),
    ("first_pcm", "First PCM"),
    ("first_audio_frame", "First audio frame"),
)
STAGES = (("input", "Input", 0, 2), ("context", "Context", 2, 6), ("output", "Output", 6, 10))
_LABELS = dict(NODES)


@dataclass(slots=True)
class TurnObservation:
    task: Task
    configuration: str
    session_id: str
    start_ns: int | None  # The response start; None when the input never went in
    timeline: SourceTimeline
    turn_id: str | None  # The Turn this input started, found by its cutoff
    records: list[OutputRecord]
    logs: list[LogRecord]
    trace: list[dict[str, Any]]
    identity: Callable[[str], str]
    ended: str | None = None  # timeout, interrupted or session_failed, when not finished
    dropped: int = 0  # Output events the sink lost
    queues: dict[str, Any] = field(default_factory=dict)
    round: int = 1  # 1 for the first turn after its runtime started, then 2, 3, ...


# The 95th percentile is given from this many samples on: with fewer, it is one of the
# largest two values, which the range already shows.
P95_SAMPLES = 20


def summarize(results: list[ScenarioResult]) -> tuple[ScenarioSummary, ...]:
    """Each scenario's rounds: how many passed, where the others stopped, and each figure
    over the passed rounds, the first apart from the later, then the same over every round
    that observed it. A merged value is a sample of neither."""
    groups: dict[tuple[str, str], list[ScenarioResult]] = {}
    for result in results:
        if result.round is not None:
            groups.setdefault((result.name, result.configuration), []).append(result)
    found = []
    for (name, configuration), rounds in groups.items():
        stopped: dict[str, int] = {}
        for r in rounds:
            if r.outcome != ScenarioOutcome.PASSED:
                stage = r.blocked_stage or r.outcome.value
                stopped[stage] = stopped.get(stage, 0) + 1
        figures: dict[str, list[tuple[ScenarioResult, Metric]]] = {}
        for r in rounds:
            for metric in (*r.metrics, *r.segments):
                figures.setdefault(metric.name, []).append((r, metric))
        summaries = []
        for figure, measured in figures.items():
            passed = [(r, m) for r, m in measured if r.outcome == ScenarioOutcome.PASSED]
            first, later = _observed(passed)
            all_first, every = _observed(measured)
            missing = [m.note for _, m in passed or measured if m.value is None and m.note]
            summaries.append(
                FigureSummary(
                    figure,
                    measured[0][1].unit,
                    first,
                    len(later),
                    round(statistics.median(later), 3) if later else None,
                    later[0] if later else None,
                    later[-1] if later else None,
                    _p95(later),
                    missing[0] if missing and first is None and not later else None,
                    all_first,
                    len(every),
                    round(statistics.median(every), 3) if every else None,
                    every[0] if every else None,
                    every[-1] if every else None,
                    sum(bool(m.merged) for _, m in measured),
                )
            )
        passed = sum(r.outcome == ScenarioOutcome.PASSED for r in rounds)
        sample = next((r.sample for r in rounds if r.sample), None)
        found.append(
            ScenarioSummary(
                name, configuration, len(rounds), passed, stopped, tuple(summaries), sample
            )
        )
    return tuple(found)


def _observed(measured: list[tuple[ScenarioResult, Metric]]) -> tuple[float | None, list[float]]:
    """Round 1's value, and the later rounds' sorted: merged values left out."""
    kept = [(r.round, m.value) for r, m in measured if m.value is not None and not m.merged]
    return next((v for at, v in kept if at == 1), None), sorted(v for at, v in kept if at != 1)


def _p95(values: list[float]) -> float | None:
    """The nearest-rank 95th percentile, from ``P95_SAMPLES`` sorted samples on."""
    if len(values) < P95_SAMPLES:
        return None
    return values[max(0, -(-95 * len(values) // 100) - 1)]


def scenario(observation: TurnObservation) -> ScenarioResult:
    turn = _Turn(observation)
    stages = turn.stages()
    blocked = next((name for name, at in stages if at is None), None)
    transcript, answer = turn.transcript(), turn.answer()
    task = observation.task
    details = turn.problems()
    sentences = turn.sentences(transcript)
    if blocked is None:
        if task.sentences and not task.heard(transcript):
            lost = [sentence for sentence in sentences if not sentence["heard"]]
            blocked = _LOST_AT.get(lost[0]["lost"] if lost else "", "transcript")
            details.append("The transcript does not hold every sentence of the sample")
            details += [f"Sentence {s['index']}: {s['why']}" for s in lost]
        elif not task.answered(answer):
            blocked = "answer"
            details.append(f"The answer is not exactly one of: {', '.join(task.answers)}")
    if observation.ended is not None:
        # The turn's own end stands: what arrived after it is evidence, not a completion.
        details.append(f"Ended by {observation.ended.replace('_', ' ')}")
        blocked = blocked or f"turn.{observation.ended}"
    if observation.ended == "interrupted":
        outcome = ScenarioOutcome.INTERRUPTED
    else:
        outcome = ScenarioOutcome.PASSED if blocked is None else ScenarioOutcome.FAILED
    metrics, segments = turn.metrics(), turn.segments()
    if outcome == ScenarioOutcome.PASSED:
        shown = {metric.name: metric.value for metric in metrics}
        summary = "; ".join(
            f"{label} {shown[name]:.0f} ms"
            for name, label in (
                ("first_text", "first text"),
                ("first_audio_frame", "first audio frame"),
                ("response_final", "complete"),
            )
            if shown.get(name) is not None
        )
        summary = f"Answered as the task expects; {summary}"
    elif outcome == ScenarioOutcome.INTERRUPTED:
        summary = f"Interrupted before {blocked}"
    else:
        summary = f"Stopped at {blocked}"
    try:
        sample = samples.identity(task.speech)
    except Exception:
        sample = None  # The session names a sample it could not read already.
    return ScenarioResult(
        name=task.name,
        outcome=outcome,
        summary=summary,
        configuration=observation.configuration,
        blocked_stage=blocked,
        cause=turn.cause(),
        details=tuple(details),
        task=task.prompt,
        transcript=transcript[:_EXCERPT] or None,
        answer=answer[:_EXCERPT] or None,
        reached=tuple(name for name, at in stages if at is not None),
        request=turn.request(),
        outputs=turn.outputs(),
        round=observation.round,
        sentences=tuple(sentences),
        metrics=metrics,
        segments=segments,
        frames=turn.frames(),
        evidence=turn.evidence(),
        sample=sample,
    )


class _Turn:
    def __init__(self, observation: TurnObservation) -> None:
        self.o = observation
        self.start = observation.start_ns
        turn_id = observation.turn_id
        self.records = [r for r in observation.records if turn_id and r.turn_id == turn_id]
        session = [
            r
            for r in observation.logs
            if r.fields.get("session_id", observation.session_id) == observation.session_id
        ]
        started = [
            r for r in session if r.name == "model.started" and r.fields.get("turn_id") == turn_id
        ]
        # The run whose request carried this Turn: its outputs are the ones checked. Its
        # first request is the one measured.
        first = started[0] if started else None
        self.run_id = first.fields.get("run_id") if first is not None else None
        self.request_id = first.fields.get("request_id") if first is not None else None
        self.answers = [
            r
            for r in self.records
            if r.lane == _ASSISTANT and (self.run_id is None or r.run_id in (self.run_id, None))
        ]
        # Speech and TTS logs carry no Turn: they belong to it through its outputs' requests.
        outputs = {r.output_id for r in self.records}
        requests = {
            r.fields.get("request_id")
            for r in session
            if r.name == "speech.request" and r.fields.get("output_id") in outputs
        }
        # The provider's own records of its request carry the Loop's request, not the Turn.
        loop_requests = {r.fields.get("request_id") for r in started}
        self.logs = [
            r
            for r in session
            if (turn_id is not None and r.fields.get("turn_id") == turn_id)
            or r.fields.get("output_id") in outputs
            or (r.name.startswith("tts.") and r.fields.get("request_id") in requests)
            or (r.name == "model.request_sent" and r.fields.get("request_id") in loop_requests)
        ]
        self.trace = self._chain(observation.trace, observation.identity, turn_id)
        if turn_id is None:
            self.trace = self._uncommitted(observation.trace, observation.timeline.started_ns)
        # The STT plugin times each request by its segment, which the trace names salted.
        segments = {r["segment_id"] for r in self.trace if r.get("segment_id")}
        self.logs += [
            r
            for r in session
            if r.name == "stt.request"
            and r.fields.get("segment_id")
            and observation.identity(r.fields["segment_id"]) in segments
        ]
        self.logs.sort(key=lambda r: r.monotonic_ns)
        self.published = {
            observation.identity(frame.observation_id): frame
            for frame in observation.timeline.frames
            if frame.kind == "screen"
        }

    def _token(self, value: str | None) -> str | None:
        return self.o.identity(value)[3:15] if value else None

    # Correlation

    @staticmethod
    def _chain(trace: list[dict], identity: Callable[[str], str], turn_id: str | None) -> list:
        if turn_id is None:
            return []
        key = identity(turn_id)
        turn = [r for r in trace if r.get("turn_id") == key]
        decisions = {r["decision_id"] for r in turn if "decision_id" in r}
        requests = {r["request_id"] for r in turn if "request_id" in r}
        candidates = {
            r["candidate_id"]
            for r in trace
            if r.get("decision_id") in decisions and "candidate_id" in r
        }
        segments = {
            r["segment_id"]
            for r in trace
            if r.get("candidate_id") in candidates and "segment_id" in r
        }
        chained = [
            r
            for r in trace
            if r.get("turn_id") == key
            or r.get("decision_id") in decisions
            or r.get("candidate_id") in candidates
            or r.get("segment_id") in segments
            or r.get("request_id") in requests
        ]
        return sorted(chained, key=lambda r: r["trace_sequence"])

    @staticmethod
    def _uncommitted(trace: list[dict], since_ns: int) -> list:
        """No Turn committed: this input as far as it went, from its own sound on, so the
        report names the stage it stopped at rather than the first after the input."""
        stages = ("perception.speech", "audio.", "stt.", "candidate.")
        return [
            r for r in trace if r["recorded_time_ns"] >= since_ns and r["stage"].startswith(stages)
        ]

    def _trace(self, stage: str, **match: object) -> dict | None:
        return next(
            (
                r
                for r in self.trace
                if r["stage"] == stage and all(r.get(k) == v for k, v in match.items())
            ),
            None,
        )

    def _log(self, name: str, **match: object) -> LogRecord | None:
        return next(
            (
                r
                for r in self.logs
                if r.name == name and all(r.fields.get(k) == v for k, v in match.items())
            ),
            None,
        )

    def _output(self, kind: str, *, last: bool = False, **match: object) -> OutputRecord | None:
        found = [
            r
            for r in self.answers
            if r.kind == kind and all(getattr(r, k) == v for k, v in match.items())
        ]
        found = [r for r in found if r.kind != "text_chunk" or r.text.strip()]
        return (found[-1] if last else found[0]) if found else None

    @staticmethod
    def _at(item: Any) -> int | None:
        if item is None:
            return None
        if isinstance(item, dict):
            return item["recorded_time_ns"]
        return item.monotonic_ns

    # The model request

    def _request(self) -> dict | None:
        """The Turn's first request, as the Loop recorded what it carries."""
        if self.request_id is None:
            return self._trace("model.request")
        return self._trace("model.request", request_id=self.o.identity(self.request_id))

    def _request_inputs(self) -> dict[str, str]:
        """Each of the Turn's input observations, as the first request recorded it: carried
        or missing. The Turn took each one it names."""
        request = self._request()
        if request is None:
            return {}
        return {
            r["observation_id"]: r.get("outcome", "")
            for r in self.trace
            if r["stage"] == "model.request_input"
            and r.get("request_id") == request["request_id"]
            and "observation_id" in r
        }

    def _request_frames(self) -> list[dict]:
        request = self._request()
        if request is None:
            return []
        return [
            r
            for r in self.trace
            if r["stage"] == "model.request_frame" and r.get("request_id") == request["request_id"]
        ]

    def _sample_frames(self) -> list[dict]:
        return [r for r in self._request_frames() if r.get("observation_id") in self.published]

    def _finals(self) -> list[dict]:
        """The STT finals the first request carries, in the order they came."""
        carried = {key for key, outcome in self._request_inputs().items() if outcome == "carried"}
        return [
            r
            for r in self.trace
            if r["stage"] == "stt.terminal"
            and r.get("outcome") == "final_text"
            and r.get("observation_id") in carried
        ]

    def _carries_content(self) -> bool:
        """The request carries this Turn's input itself: an STT final of the sample's speech."""
        return bool(self._finals())

    def _carries_input(self) -> bool:
        request, committed = self._request(), self._trace("turn.committed")
        return (
            request is not None
            and committed is not None
            and request.get("input_id") is not None
            and request.get("input_id") == committed.get("input_id")
        )

    def _attempts(self) -> list[LogRecord]:
        """The first request as its provider sent it: each attempt, as it went to the
        transport. Only providers that log it, the OpenAI Responses one."""
        return [
            r
            for r in self.logs
            if r.name == "model.request_sent" and r.fields.get("request_id") == self.request_id
        ]

    def request(self) -> dict[str, str | int | bool]:
        request = self._request()
        if request is None:
            return {}
        return {
            "turn": request["turn_id"][3:15],
            "run": request.get("run_id", "")[3:15],
            "request": request["request_id"][3:15],
            "carries_turn_input": self._carries_input(),
            "carries_turn_content": self._carries_content(),
            "frames": request.get("frame_count", 0),
            "sample_frames": len(self._sample_frames()),
            "requests": sum(r["stage"] == "model.request" for r in self.trace),
            "attempts": len(self._attempts()),
            "finals": len(self._finals()),
        }

    # Outputs

    def _terminals(self) -> list[tuple[str, str, str, str | None, int | None]]:
        """Each output of the run: its id, modalities, how and why it ended, and when."""
        ids = list(dict.fromkeys(r.output_id for r in self.answers if r.kind in _CONTENT))
        found = []
        for output_id in ids:
            kinds = {r.kind for r in self.answers if r.output_id == output_id}
            modalities = "+".join(
                name
                for kind, name in zip(_CONTENT, ("text", "audio"), strict=True)
                if kind in kinds
            )
            complete = next(
                (
                    r
                    for r in self.answers
                    if r.kind == "control" and r.control == "complete" and r.output_id == output_id
                ),
                None,
            )
            # An interruption carries no Turn of its own: it names the outputs it ends.
            interrupt = next(
                (
                    r
                    for r in self.o.records
                    if r.kind == "control" and r.control == "interrupt" and output_id in r.targets
                ),
                None,
            )
            if complete is not None and (
                interrupt is None or complete.monotonic_ns <= interrupt.monotonic_ns
            ):
                found.append((output_id, modalities, "completed", None, complete.monotonic_ns))
            elif interrupt is not None and interrupt.reason == TURN_ENDED:
                # Doctor's own interruption: the turn had already ended otherwise.
                terminal = _UNFINISHED.get(self.o.ended or "", "not_ended")
                found.append((output_id, modalities, terminal, None, None))
            elif interrupt is not None:
                failed = (interrupt.reason or "").endswith("_failed")
                terminal = "failed" if failed else "interrupted"
                found.append(
                    (output_id, modalities, terminal, interrupt.reason, interrupt.monotonic_ns)
                )
            else:
                terminal = _UNFINISHED.get(self.o.ended or "", "not_ended")
                found.append((output_id, modalities, terminal, None, None))
        return found

    def _completed_at(self) -> int | None:
        """When the last output ended, if every output of the run ended normally."""
        terminals = self._terminals()
        if not terminals or any(item[2] != "completed" for item in terminals):
            return None
        return max(item[4] for item in terminals)

    def outputs(self) -> tuple[dict[str, str | float | None], ...]:
        return tuple(
            {
                "output": self._token(output_id),
                "modalities": modalities,
                "terminal": terminal,
                "reason": reason,
                "at_ms": round((at - self.start) / 1e6, 3)
                if at is not None and self.start is not None
                else None,
            }
            for output_id, modalities, terminal, reason, at in self._terminals()
        )

    def problems(self) -> list[str]:
        lines = [
            f"Output {self._token(output_id)} ({modalities}) {terminal.replace('_', ' ')}"
            + (f": {reason}" if reason else "")
            for output_id, modalities, terminal, reason, _ in self._terminals()
            if terminal != "completed"
        ]
        if self._request() is not None and not self._carries_input():
            lines.append("The model request does not carry this Turn's committed input")
        if self._request() is not None and not self._carries_content():
            lines.append("The model request does not carry this Turn's transcript")
        if self.o.task.screen and self._request() is not None and not self._sample_frames():
            lines.append("The model request carries none of the sample's frames")
        finished = self._log("run.finished")
        if finished is not None and finished.fields.get("state") != "completed":
            cause = self.cause()
            lines.append(
                f"The run ended {finished.fields.get('state')}" + (f": {cause}" if cause else "")
            )
        return lines

    def cause(self) -> str | None:
        """What stopped the turn, as its producer names it: the run's error, else an output's."""
        finished = self._log("run.finished")
        if finished is not None and finished.fields.get("state") != "completed":
            kind, code = finished.fields.get("error_type"), finished.fields.get("error_code")
            if kind and code:
                return f"{kind}: {code}"  # As the provider classified it, e.g. http_401.
            return kind or finished.fields.get("reason")
        return next(
            (reason for _, _, terminal, reason, _ in self._terminals() if terminal == "failed"),
            None,
        )

    def stages(self) -> list[tuple[str, int | None]]:
        task = self.o.task
        stages: list[tuple[str, int | None]] = [
            ("input", self.start),
            ("vad.closed", self._at(self._trace("perception.speech_closed"))),
            ("stt.final", self._at(self._trace("stt.terminal", outcome="final_text"))),
            ("turn.committed", self._at(self._trace("turn.committed"))),
        ]
        if task.screen:
            visual = self._trace("context.visual")
            selected = visual is not None and visual.get("frame_count", 0) > 0
            stages.append(("frames.selected", self._at(visual) if selected else None))
        request = self._request()
        stages += [
            ("model.request", self._at(self._log("model.started"))),
            ("request.input", self._at(request) if self._carries_input() else None),
            ("request.content", self._at(request) if self._carries_content() else None),
        ]
        if task.screen:
            stages.append(("request.frames", self._at(request) if self._sample_frames() else None))
        stages += [
            ("model.first_event", self._at(self._log("model.first_event"))),
            ("text.first", self._at(self._output("text_chunk"))),
            ("text.complete", self._at(self._output("control", control="text_complete"))),
            ("audio.first", self._at(self._output("audio_frame"))),
            ("outputs.complete", self._completed_at()),
        ]
        finished = self._log("run.finished")
        ok = finished is not None and finished.fields.get("state") == "completed"
        stages.append(("run.completed", self._at(finished) if ok else None))
        return stages

    def transcript(self) -> str:
        committed = self._log("input.committed")
        return committed.text if committed is not None else ""

    def sentences(self, transcript: str) -> list[dict[str, Any]]:
        """Each sentence of the spoken prompt, heard in the transcript or not, and what each
        layer recorded of it, apart:

        - ``coverage``: how much of its sound closed speech segments hold, ``full``,
          ``partial`` or ``none``; None when its sound cannot be placed;
        - ``stt``: whether STT returned a final for a segment holding it (``final``), none
          (``no_final``, or how its segments ended), or only after its Turn (``late``);
        - ``adopted``: whether the Turn took that final, as its first request names it;
        - ``content``: whether the final the Turn took holds its words; None when no final
          was taken, as its text is not seen.

        A sentence not heard is placed in the first layer that lost it: ``vad`` when no
        segment, or only part of one, holds its sound; ``stt`` when no final came for it in
        time, or the final taken leaves its words out; ``turn`` when its final came but the
        Turn did not take it; ``unknown`` when the evidence shows none of these. A
        sentence's sound is the recording's voiced stretch of that order; where the
        stretches do not match the sentences one to one, every segment may hold any.
        """
        task, timeline = self.o.task, self.o.timeline
        if not task.sentences or not timeline.started_ns:
            return []
        heard = task.heard_sentences(transcript)
        try:
            spans = samples.speech(task.speech).spans
        except Exception:
            spans = ()
        spans = spans if len(spans) == len(heard) else ()
        started = timeline.started_ns
        window = [r for r in self.o.trace if r["recorded_time_ns"] >= started]
        closed = [
            r for r in window if r["stage"] == "perception.speech_closed" and "segment_id" in r
        ]
        terminals = {
            r["segment_id"]: r for r in window if r["stage"] == "stt.terminal" and "segment_id" in r
        }
        late = {
            r["segment_id"]
            for r in window
            if "segment_id" in r
            and (
                r["stage"] == "candidate.transcript_rejected"
                or (r["stage"] == "stt.stale" and r.get("reason") == "segment_retired")
            )
        }
        taken = set(self._request_inputs())
        committed = self._at(self._trace("turn.committed"))

        def holding(index: int) -> tuple[list[dict], str | None, int]:
            """The segments over its sound, how much they cover, and the overlap in ms."""
            if not spans:
                return closed, None, 0
            begin, end = (started + round(at * 1e9) for at in spans[index])
            overlaps = []
            for r in closed:
                low = max(begin, r.get("start_time_ns", end))
                high = min(end, r.get("end_time_ns", begin))
                if high > low:
                    overlaps.append((r, high - low))
            covered = sum(ns for _, ns in overlaps)
            share = covered / (end - begin) if end > begin else 0.0
            coverage = "none" if not overlaps else "full" if share >= _COVERED else "partial"
            return [r for r, _ in overlaps], coverage, round(covered / 1e6)

        found = []
        for index, was_heard in enumerate(heard):
            segments, coverage, covered = holding(index)
            keys = [r["segment_id"] for r in segments]
            ends = [terminals.get(key) for key in keys]
            finals = [t for t in ends if t is not None and t.get("outcome") == "final_text"]
            on_time = [
                t
                for t in finals
                if t["segment_id"] not in late
                and (committed is None or t["recorded_time_ns"] <= committed)
            ]
            adopted = [t for t in on_time if t.get("observation_id") in taken]
            if finals and not on_time:
                stt = "late"
            elif finals:
                stt = "final"
            elif any(key in late for key in keys):
                stt = "late"
            else:
                outcomes = sorted({t.get("outcome") for t in ends if t is not None})
                stt = ", ".join(outcomes) if outcomes else "no_final" if segments else None
            entry: dict[str, Any] = {
                "index": index + 1,
                "heard": was_heard,
                "span_ms": [round(at * 1000) for at in spans[index]] if spans else None,
                "segments": [key[3:15] for key in keys],
                "coverage": coverage,
                "covered_ms": covered if spans else None,
                "stt": stt,
                "adopted": bool(adopted) if segments else None,
                "content": None,
                "lost": None,
                "why": None,
            }
            if adopted:
                entry["content"] = "holds_its_words" if was_heard else "lacks_its_words"
            if not was_heard:
                entry["lost"], entry["why"] = _lost(entry, adopted, heard, index, holding)
            found.append(entry)
        return found

    def answer(self) -> str:
        return "".join(r.text for r in self.answers if r.kind == "text_chunk")

    # Metrics

    def _metric(
        self,
        name: str,
        start: tuple[str, int | None],
        end: tuple[str, int | None],
        boundary: str,
        missing: str | None = None,
        *,
        note: str | None = None,
    ) -> Metric:
        """``missing`` says why there is no value, ``note`` what one is: a figure carries one."""
        value = None
        if start[1] is not None and end[1] is not None:
            value = round((end[1] - start[1]) / 1e6, 3)
        samples = int(value is not None)
        note = missing if value is None else note
        return Metric(name, value, "ms", start[0], end[0], boundary, samples, note=note)

    def metrics(self) -> tuple[Metric, ...]:
        origin = ("last voiced sample in", self.start)
        boundary = "diagnostic input to the output boundary, server side"
        text, audio = self._output("text_chunk"), self._output("audio_frame")
        # Completion is recorded only for a turn that completed, every output of it normally.
        completed = self._completed_at() if self.o.ended is None else None
        unfinished = None
        if completed is None:
            unfinished = (
                f"not recorded: the turn ended by {self.o.ended.replace('_', ' ')}"
                if self.o.ended is not None
                else "not recorded: an output ended otherwise"
            )
        texts = [r for r in self.answers if r.kind == "control" and r.control == "text_complete"]
        last_audio = self._output("audio_frame", last=True)
        metrics = [
            self._metric("first_text", origin, ("first answer text out", self._at(text)), boundary),
            self._metric(
                "first_audio_frame",
                origin,
                ("first answer audio frame out", self._at(audio)),
                boundary,
            ),
            Metric(
                "first_visual_output_frame",
                None,
                "ms",
                origin[0],
                "first visual output frame out",
                boundary,
                0,
                note="no visual output reaches the output boundary",
            ),
            self._metric(
                "text_complete",
                origin,
                ("last text complete", self._at(texts[-1]) if texts and completed else None),
                boundary,
                unfinished,
            ),
            self._metric(
                "audio_last_frame",
                origin,
                ("last answer audio frame out", self._at(last_audio) if completed else None),
                boundary,
                unfinished,
            ),
            self._metric(
                "response_final", origin, ("every output complete", completed), boundary, unfinished
            ),
        ]
        selected = [frame for frame in self._frames() if frame["selected"] and frame["frame"]]
        if self.o.task.screen and selected and self.start is not None:
            last = max(frame["frame"].published_ns for frame in selected)
            metrics.append(
                self._metric(
                    "last_required_input",
                    origin,
                    ("last selected frame or voiced sample in", max(last, self.start)),
                    "diagnostic input",
                    "0 when every selected frame arrived before the speech ended",
                )
            )
        metrics += self._audio_supply()
        return tuple(metrics)

    def _audio_supply(self) -> list[Metric]:
        frames = [r for r in self.answers if r.kind == "audio_frame"]
        if not frames:
            return []
        times = [r.monotonic_ns for r in frames]
        gaps = [(b - a) / 1e6 for a, b in zip(times, times[1:], strict=False)]
        duration = sum(r.audio_sec for r in frames)
        queues = [self.o.queues[r] for r in {r.output_id for r in frames} if r in self.o.queues]
        boundary = "answer audio frames at the output boundary"
        produced = (times[-1] - times[0]) / 1e9
        return [
            Metric(
                "audio_duration",
                round(duration, 3),
                "s",
                "first frame",
                "last frame",
                boundary,
                len(frames),
            ),
            Metric(
                "audio_frame_interval",
                round(statistics.median(gaps), 3) if gaps else None,
                "ms",
                "frame out",
                "next frame out",
                boundary,
                len(gaps),
                note="median",
            ),
            Metric(
                "audio_max_gap",
                round(max(gaps), 3) if gaps else None,
                "ms",
                "frame out",
                "next frame out",
                boundary,
                len(gaps),
            ),
            Metric(
                "audio_underruns",
                float(sum(q.underruns for q in queues)),
                "count",
                "first frame out",
                "last frame out",
                "a real-time queue started at the first frame, without startup buffering",
                len(frames),
                note=f"{sum(q.underrun_ms for q in queues):.1f} ms starved in total",
            ),
            Metric(
                "audio_rtf",
                round(produced / duration, 4) if duration else None,
                "ratio",
                "first frame out",
                "last frame out",
                boundary,
                len(frames) if duration else 0,
                note=f"{produced:.3f} s producing over {duration:.3f} s of audio",
            ),
            Metric(
                "output_events_dropped",
                float(self.o.dropped),
                "count",
                "session ready",
                "turn end",
                "the diagnostic sink's subscription",
                note="a reliable subscription: a slow sink holds producers back, it drops nothing",
            ),
        ]

    def nodes(self) -> dict[str, tuple[int | None, str | None]]:
        """Each node of the chain, for the Turn's first model request: when, or why not."""
        finals = self._finals()
        final = max(finals, key=lambda r: r["recorded_time_ns"]) if finals else None
        closed = (
            self._trace("perception.speech_closed", segment_id=final["segment_id"])
            if final is not None and "segment_id" in final
            else None
        )
        request = self._request()
        started = self._log("model.started", request_id=self.request_id)
        built = self._log("context.built", request_id=self.request_id)
        sent = self._attempts()
        delta = self._log("model.first_text", request_id=self.request_id)
        # The outputs whose text the first request streamed, and the first audio of those.
        ours = {
            r.output_id
            for r in self.answers
            if r.kind == "text_chunk" and r.request_id == self.request_id
        }
        audio = next(
            (r for r in self.answers if r.kind == "audio_frame" and r.output_id in ours), None
        )
        first_audio = self._output("audio_frame")
        speech = self._log("speech.request", output_id=audio.output_id) if audio else None
        tts = speech.fields.get("request_id") if speech is not None else None
        pcm = self._log("tts.first_pcm", request_id=tts) if tts else None
        no_request = "no model request for the Turn"
        if audio is None:
            unanswered = "no audio frame answers the first model request"
        elif audio is not first_audio:
            unanswered, audio = "the first audio frame answers a later model request", None
        else:
            unanswered = None
        return {
            "speech_end": (self.start, "the frame with the last voiced sample did not go in"),
            "vad_close": (
                self._at(closed),
                "the request carries no STT final"
                if final is None
                else "its segment's close was not recorded",
            ),
            "final_transcript": (
                self._at(final),
                no_request if request is None else "the first model request carries no STT final",
            ),
            "turn_commit": (self._at(self._trace("turn.committed")), "no Turn committed"),
            "context_ready": (
                self._at(self._log("context.ready")),
                "Context logged no readiness check for the Turn",
            ),
            "context_built": (
                self._at(built),
                no_request if started is None else "the loop logs no context built",
            ),
            "request_sent": (
                self._at(sent[0]) if sent else None,
                no_request if started is None else "its provider logs no request sent",
            ),
            "first_text_delta": (self._at(delta), "the first model request streamed no text"),
            "tts_request": (self._at(speech), "no TTS request for the first request's answer"),
            "first_pcm": (
                self._at(pcm),
                "this TTS plugin logs no first PCM" if speech is not None else "no TTS request",
            ),
            "first_audio_frame": (self._at(audio), unanswered),
        }

    def chain(self) -> list[Metric]:
        """The stages, then each row of each, from the chain's nodes (see the module)."""
        nodes, found = self.nodes(), []
        boundary = "the Turn's first model request, one clock"
        for stage, _, first, last in STAGES:
            keys = [key for key, _ in NODES[first : last + 1]]
            (start, start_why), (end, end_why) = nodes[keys[0]], nodes[keys[-1]]
            missing = None
            if start is None:
                missing = f"not measured: {_LABELS[keys[0]]} not observed: {start_why}"
            elif end is None:
                missing = f"not measured: {_LABELS[keys[-1]]} not observed: {end_why}"
            elif end < start:
                missing = f"not measured: {_LABELS[keys[-1]]} came before {_LABELS[keys[0]]}"
            value = None if missing else round((end - start) / 1e6, 3)
            found.append(
                Metric(
                    stage,
                    value,
                    "ms",
                    _LABELS[keys[0]],
                    _LABELS[keys[-1]],
                    boundary,
                    int(value is not None),
                    note=missing,
                )
            )
            previous, merged = (keys[0] if start is not None else None), []
            for key in keys[1:]:
                at, why = nodes[key]
                since = nodes[previous][0] if previous is not None else None
                name, origin = f"{stage}.{key}", _LABELS[previous or keys[0]]
                inner = key != keys[-1]
                early = at is not None and (
                    (since is not None and at < since) or (end is not None and at > end)
                )
                if inner and (at is None or early):
                    reason = f"not observed: {why}" if at is None else "came out of order"
                    note = f"merged into the next row: {_LABELS[key]} {reason}"
                    found.append(
                        Metric(name, None, "ms", origin, _LABELS[key], boundary, 0, note=note)
                    )
                    merged.append(key)
                    continue
                if at is None:
                    note = f"not measured: {_LABELS[key]} not observed: {why}"
                elif since is None:
                    note = f"not measured: {_LABELS[keys[0]]} not observed: {start_why}"
                elif at < since:
                    note = f"not measured: {_LABELS[key]} came before {origin}"
                else:
                    note = None
                value = None if note else round((at - since) / 1e6, 3)
                if note is None and merged:
                    note = f"from {origin}: {', '.join(_LABELS[k] for k in merged)} merged"
                found.append(
                    Metric(
                        name,
                        value,
                        "ms",
                        origin,
                        _LABELS[key],
                        boundary,
                        int(value is not None and not merged),
                        note=note,
                        # Only a value ran from an earlier node; a row not measured says why.
                        merged=tuple(merged) if value is not None else (),
                    )
                )
                merged = []
                if at is not None:
                    previous = key
        return found

    def _stt(self, final: dict | None) -> list[Metric]:
        """Where the STT request of the final the Turn's request took spent its time: its
        wait in the plugin's queue, the connection it opened (none when reused), the upload,
        the wait for the answer and the answer's stream to the final. A request its transport
        did not trace has its queue alone; the rest is not observed, reuse included."""
        timed = next(
            (
                r
                for r in self.logs
                if r.name == "stt.request"
                and final is not None
                and self.o.identity(r.fields.get("segment_id")) == final.get("segment_id")
            ),
            None,
        )
        why = "no STT final for the Turn" if final is None else "its STT plugin times no request"
        boundary = "the STT request of the Turn's final, as its plugin times it"
        rows = (
            ("stt_queue", "queue_ms", "segment committed", "request started"),
            ("stt_connect", "connect_ms", "connection opening", "connection open"),
            ("stt_tls", "tls_ms", "TLS handshake started", "TLS handshake done"),
            ("stt_upload", "upload_ms", "request headers sent", "audio sent"),
            ("stt_wait", "wait_ms", "audio sent", "answer's headers"),
            ("stt_first_event", "first_event_ms", "answer's headers", "first stream event"),
            ("stt_stream", "final_ms", "answer's headers", "transcript done"),
        )
        found = []
        for name, key, start, end in rows:
            value = timed.fields.get(key) if timed is not None else None
            # Reuse is known from a request its transport traced; one it did not is neither.
            reused = timed.fields.get("reused") if timed is not None else None
            if timed is None:
                note = f"not measured: {why}"
            elif value is not None:
                note = None
            elif key in ("connect_ms", "tls_ms") and reused is True:
                note = "none: the connection was reused"
            elif key == "tls_ms" and reused is False:
                note = "none: the connection has no TLS"
            elif reused is None:
                note = "not observed: its transport traced no request"
            else:
                note = "not measured: its STT plugin times no such step"
            found.append(
                Metric(name, value, "ms", start, end, boundary, int(value is not None), note=note)
            )
        return found

    def segments(self) -> tuple[Metric, ...]:
        """The chain's stages and rows, then what the rows leave out: STT's own wait, the
        readiness wait, the request as sent, its first event, the frames."""
        segments = self.chain()
        finals = self._finals()
        final = max(finals, key=lambda r: r["recorded_time_ns"]) if finals else None
        commit = (
            self._trace("stt.commit", segment_id=final["segment_id"])
            if final is not None and "segment_id" in final
            else None
        )
        segments += [
            self._metric(
                "stt_request_to_final",
                ("segment committed to STT", self._at(commit)),
                ("STT final", self._at(final)),
                "input trace",
                "the commit of the request's last final was not recorded",
            ),
            *self._stt(final),
            Metric(
                "input_lateness",
                round(self.o.timeline.max_lateness_ms, 3),
                "ms",
                "frame due",
                "frame published",
                "the diagnostic source's cadence, at worst",
                self.o.timeline.audio_frames,
            ),
        ]
        ready = self._log("context.ready")
        wait = ready.fields.get("wait_ms") if ready is not None else None
        attempts = self._attempts()
        sent = attempts[0] if attempts else None
        first_event = self._log("model.first_event", request_id=self.request_id)
        kind = first_event.fields.get("event_kind") if first_event is not None else None
        segments += [
            Metric(
                "context_ready_wait",
                round(float(wait), 3) if wait is not None else None,
                "ms",
                "Context asked for the Turn's context",
                "context ready",
                "Context manager log",
                int(wait is not None),
                note=None if wait is None else "how long registered context work held it back",
            ),
            *self._request_sent(sent, len(attempts)),
            self._metric(
                "model_first_event",
                ("model request sent", self._at(sent)),
                ("first model stream event", self._at(first_event)),
                "provider and loop logs",
                "its provider logs no request sent" if sent is None else "no stream event",
                # Possibly only that the response began: the first text delta says more.
                note=f"its kind: {kind}" if kind else None,
            ),
        ]
        if self.o.task.screen:
            segments += self._vision(self._at(self._trace("turn.committed")))
        return tuple(segments)

    def _vision(self, committed_at: int | None) -> list[Metric]:
        encode = [f.encode_ms for f in self.o.timeline.frames if f.kind == "screen"]
        frames = [frame for frame in self._frames() if frame["selected"] and frame["frame"]]
        ages = [f["age_at_request_ms"] for f in frames if f.get("age_at_request_ms") is not None]
        lead = None
        if frames and committed_at is not None:
            last = max(frame["frame"].published_ns for frame in frames)
            lead = round((committed_at - last) / 1e6, 3)
        return [
            Metric(
                "frame_input_to_available",
                round(statistics.median(encode), 3) if encode else None,
                "ms",
                "frame arrived",
                "frame published to perception",
                "the diagnostic source: JPEG encoding, as the RTC video input",
                len(encode),
                note="median",
            ),
            Metric(
                "selected_frame_age",
                round(max(ages), 3) if ages else None,
                "ms",
                "frame arrived",
                "model request",
                "frames Context selected, oldest",
                len(ages),
                values=tuple(ages),
            ),
            Metric(
                "last_selected_frame_to_cutoff",
                lead,
                "ms",
                "newest selected frame in",
                "turn committed",
                "diagnostic input to the input trace",
                int(lead is not None),
                note="negative: that frame arrived after the cutoff",
            ),
            Metric(
                "vision_wait",
                None,
                "ms",
                "turn committed",
                "frames available",
                "the request's wait for frames after the cutoff",
                0,
                note="no wait is observed: Context selects among frames already in",
            ),
        ]

    def _request_sent(self, sent: LogRecord | None, attempts: int) -> list[Metric]:
        """The first request as its provider sent it: encoding time here, the pictures it
        carries, the body's size and the attempts it took."""
        fields = sent.fields if sent is not None else {}
        missing = (
            None
            if sent is not None
            else "no record of it sent: none went out, or its provider logs none"
        )
        found = []
        for name, key, unit, what in (
            ("model_request_encode", "encode_ms", "ms", "the request encoded here"),
            ("model_request_frames", "frame_count", "frames", "pictures the request carries"),
            ("model_request_bytes", "request_bytes", "bytes", "the body the transport sent"),
        ):
            value = fields.get(key)
            found.append(
                Metric(
                    name,
                    value,
                    unit,
                    "model request",
                    what,
                    "provider log",
                    int(value is not None),
                    note=missing if value is None else None,
                )
            )
        found.append(
            Metric(
                "model_request_attempts",
                float(attempts) if sent is not None else None,
                "count",
                "first attempt sent",
                "last attempt sent",
                "provider log",
                int(sent is not None),
                note=missing,
            )
        )
        return found

    # Frames

    def _frames(self) -> list[dict[str, Any]]:
        """Frames Context selected and frames the request carries, matched to Doctor's own."""
        selected = {
            r["observation_id"]: r
            for r in self.trace
            if r["stage"] == "context.frame_selected" and "observation_id" in r
        }
        requested = {r["observation_id"] for r in self._request_frames() if "observation_id" in r}
        request = self._at(self._log("model.started"))
        found = []
        for key in dict.fromkeys((*selected, *requested)):
            frame = self.published.get(key)
            item: dict[str, Any] = {
                "observation": key[3:15],
                "sequence": frame.sequence if frame else selected.get(key, {}).get("sequence", 0),
                "published": frame is not None,
                "selected": key in selected,
                "requested": key in requested,
                "frame": frame,
            }
            if frame is not None:
                if self.start is not None:
                    item["offset_from_speech_end_ms"] = round((frame.end_ns - self.start) / 1e6, 3)
                if request is not None:
                    item["age_at_request_ms"] = round((request - frame.end_ns) / 1e6, 3)
            found.append(item)
        return sorted(found, key=lambda item: item["sequence"])

    def frames(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            {key: value for key, value in frame.items() if key != "frame"}
            for frame in self._frames()
        )

    # Evidence

    def evidence(self) -> tuple[Evidence, ...]:
        if self.start is None:
            return ()
        items: list[tuple[int, str, str, dict]] = []
        timeline = self.o.timeline
        items.append((timeline.started_ns, "input.audio_started", "input", {}))
        items.append((self.start, "input.voiced_end", "input", {}))
        screens = [frame for frame in timeline.frames if frame.kind == "screen"]
        if screens:
            items.append(
                (
                    screens[0].published_ns,
                    "input.screen_first",
                    "input",
                    {"sequence": screens[0].sequence},
                )
            )
        for record in self.trace:
            detail = {
                key: record[key]
                for key in (
                    "sequence",
                    "cutoff_sequence",
                    "frame_count",
                    "action",
                    "outcome",
                    "reason",
                    "text_chars",
                )
                if key in record
            }
            # The trace's own salted identities, shortened: equal tokens are one identity.
            for key in (
                "turn_id",
                "decision_id",
                "candidate_id",
                "segment_id",
                "input_id",
                "run_id",
                "request_id",
                "observation_id",
            ):
                if key in record:
                    detail[key.removesuffix("_id")] = record[key][3:15]
            items.append((record["recorded_time_ns"], record["stage"], "trace", detail))
        # Outputs and logs carry raw identities; the trace's tokens for them join them up.
        turn = self._token(self.o.turn_id)
        seen: set[str] = set()
        for record in self.logs:
            key = record.name
            if record.name in ("speech.segment", "speech.request"):
                key = f"{record.name}:{record.fields.get('output_id')}"
            elif record.name == "model.request_sent":  # Each attempt, as it went out
                fields = record.fields
                key = f"{record.name}:{fields.get('request_id')}:{fields.get('attempt')}"
            if key in seen:
                continue
            seen.add(key)
            detail = {
                k: v
                for k, v in record.fields.items()
                if k in ("state", "reason", "error_type", "event_kind", "segment", "attempt")
            }
            if turn is not None and record.fields.get("turn_id") == self.o.turn_id:
                detail["turn"] = turn
            for name in ("run_id", "request_id"):
                if record.name.startswith(("model.", "run.", "context.")) and record.fields.get(
                    name
                ):
                    detail[name.removesuffix("_id")] = self._token(record.fields[name])
            items.append((record.monotonic_ns, record.name, "log", detail))
        firsts: set[tuple[str, str | None]] = set()
        for record in self.records:
            key = (record.kind, record.control or record.playback)
            if key in firsts and record.kind in ("text_chunk", "audio_frame", "playback"):
                continue
            firsts.add(key)
            detail = {"lane": record.lane}
            if turn is not None:
                detail["turn"] = turn
            if record.run_id:
                detail["run"] = self._token(record.run_id)
            if record.request_id:
                detail["request"] = self._token(record.request_id)
            if record.control or record.playback:
                detail["type"] = record.control or record.playback
            items.append((record.monotonic_ns, f"output.{record.kind}", "output", detail))
        ids = {output_id for output_id, *_ in self._terminals()}
        for record in self.o.records:
            if record.control == "interrupt" and ids.intersection(record.targets):
                detail = {"type": "interrupt", "reason": record.reason or ""}
                items.append((record.monotonic_ns, "output.control", "output", detail))
        audio = [r for r in self.answers if r.kind == "audio_frame"]
        if audio:
            items.append(
                (audio[-1].monotonic_ns, "output.audio_frame_last", "output", {"lane": _ASSISTANT})
            )
        items.sort(key=lambda item: item[0])
        if len(items) > _EVIDENCE:
            # Bounded: the chain's key steps and its end stay; the earliest others fill up.
            key = [item for item in items if item[1] in _TERMINAL][:_EVIDENCE]
            rest = [item for item in items if item[1] not in _TERMINAL]
            items = sorted(key + rest[: _EVIDENCE - len(key)], key=lambda item: item[0])
        return tuple(
            Evidence(round((at - self.start) / 1e6, 3), stage, source, detail)
            for at, stage, source, detail in items
        )


def _lost(
    entry: dict[str, Any],
    adopted: list[dict],
    heard: tuple[bool, ...],
    index: int,
    holding: Callable[[int], tuple[list[dict], str | None, int]],
) -> tuple[str, str]:
    """The first layer that lost a sentence not heard, and why, from its entry's evidence."""
    if entry["coverage"] == "none":
        return "vad", "no speech segment covered its sound"
    if entry["coverage"] == "partial":
        return "vad", f"speech segments held {entry['covered_ms']} ms of its sound, not all of it"
    if not entry["segments"]:
        return "vad", "no speech segment closed"
    if entry["stt"] == "late":
        return "turn", "its STT final came after the Turn committed, for a segment it had retired"
    if entry["stt"] != "final":
        return "stt", f"no STT final for its segment: {entry['stt']}"
    if not adopted:
        return "turn", "its STT final came in time, but the Turn did not take it"
    if entry["coverage"] is None:
        return "unknown", (
            "the final the Turn took lacks its words, but its sound cannot be placed: the "
            "recording's voiced stretches do not match its sentences"
        )
    mine = {t["segment_id"] for t in adopted}
    shared = any(
        other != index and heard[other] and mine & {r["segment_id"] for r in holding(other)[0]}
        for other in range(len(heard))
    )
    chars = ", ".join(str(t.get("text_chars", "?")) for t in adopted)
    if shared:
        return "stt", (
            f"the final the Turn took ({chars} characters) holds another sentence too, "
            "and leaves this one out"
        )
    return "stt", f"the final the Turn took ({chars} characters) lacks its words"
