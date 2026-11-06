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
share. The model request's own records name the committed input, which of the Turn's input
observations it carries (the transcript of the sample's speech is one), and the frames it
carries: those frames are matched to the ones Doctor published and told apart from the ones
Context selected. Each output of the Turn's run ends normally, by failure, by interruption or
not at all. A turn that ended otherwise (a timeout, an interruption, a failed session) keeps
that end, whatever arrived after it; only a turn that completed has completion times. Every time is
``time.monotonic_ns``; intervals are milliseconds from the response start: the frame carrying
the last voiced sample, or the typed input's acceptance.
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
        "run.finished",
        "output.control",
        "output.audio_frame_last",
    )
)
_UNFINISHED = {"timeout": "timed_out", "interrupted": "interrupted"}
# Where a sentence that is not in the transcript was lost, as the stage the scenario stopped at.
_LOST_AT = {"vad": "vad.closed", "stt": "stt.final", "turn": "turn.committed"}
# Why Doctor ends the outputs of a turn that did not end on its own.
TURN_ENDED = "doctor_turn_ended"


@dataclass(slots=True)
class TurnObservation:
    task: Task
    configuration: str
    session_id: str
    start_ns: int | None  # The response start; None when the input never went in
    timeline: SourceTimeline | None
    turn_id: str | None  # The Turn this input started, found by its cutoff
    records: list[OutputRecord]
    logs: list[LogRecord]
    trace: list[dict[str, Any]]
    identity: Callable[[str], str]
    audio_output: bool
    ended: str | None = None  # timeout, interrupted or session_failed, when not finished
    dropped: int = 0  # Output events the sink lost
    queues: dict[str, Any] = field(default_factory=dict)
    round: int = 1  # 1 for the first turn after its runtime started, then 2, 3, ...


# The 95th percentile is given from this many samples on: with fewer, it is one of the
# largest two values, which the range already shows.
P95_SAMPLES = 20


def summarize(results: list[ScenarioResult]) -> tuple[ScenarioSummary, ...]:
    """Each scenario's rounds on each configuration: how many passed, where the others
    stopped, and each figure over the passed rounds, the first apart from the later."""
    groups: dict[tuple[str, str], list[ScenarioResult]] = {}
    for result in results:
        if result.round is not None:
            groups.setdefault((result.name, result.configuration), []).append(result)
    found = []
    for (name, configuration), rounds in groups.items():
        passed = [r for r in rounds if r.outcome == ScenarioOutcome.PASSED]
        stopped: dict[str, int] = {}
        for r in rounds:
            if r.outcome != ScenarioOutcome.PASSED:
                stage = r.blocked_stage or r.outcome.value
                stopped[stage] = stopped.get(stage, 0) + 1
        figures: dict[str, list[tuple[int | None, Metric]]] = {}
        for r in passed:
            for metric in (*r.metrics, *r.segments):
                figures.setdefault(metric.name, []).append((r.round, metric))
        summaries = []
        for figure, measured in figures.items():
            unit = measured[0][1].unit
            first = next((m.value for at, m in measured if at == 1), None)
            later = sorted(m.value for at, m in measured if at != 1 and m.value is not None)
            notes = [m.note for _, m in measured if m.value is None and m.note]
            summaries.append(
                FigureSummary(
                    figure,
                    unit,
                    first,
                    len(later),
                    round(statistics.median(later), 3) if later else None,
                    later[0] if later else None,
                    later[-1] if later else None,
                    _p95(later),
                    notes[0] if notes and first is None and not later else None,
                )
            )
        found.append(
            ScenarioSummary(
                name, configuration, len(rounds), len(passed), stopped, tuple(summaries)
            )
        )
    return tuple(found)


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
        if task.speech is not None and task.sentences and not task.heard(transcript):
            lost = [sentence for sentence in sentences if not sentence["heard"]]
            blocked = _LOST_AT.get(lost[0]["lost"] if lost else "stt", "stt.final")
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
        started = next(
            (
                r
                for r in session
                if r.name == "model.started" and r.fields.get("turn_id") == turn_id
            ),
            None,
        )
        # The run whose request carried this Turn: its outputs are the ones checked.
        self.run_id = started.fields.get("run_id") if started is not None else None
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
        # The provider's own record of its request carries the Loop's request, not the Turn.
        loop_requests = {
            r.fields.get("request_id")
            for r in session
            if r.name == "model.started" and r.fields.get("turn_id") == turn_id
        }
        self.logs = [
            r
            for r in session
            if (turn_id is not None and r.fields.get("turn_id") == turn_id)
            or r.fields.get("output_id") in outputs
            or (r.name.startswith("tts.") and r.fields.get("request_id") in requests)
            or (r.name == "model.request_sent" and r.fields.get("request_id") in loop_requests)
        ]
        self.trace = self._chain(observation.trace, observation.identity, turn_id)
        if turn_id is None and observation.timeline is not None:
            self.trace = self._uncommitted(observation.trace, observation.timeline.started_ns)
        self.published = {
            observation.identity(frame.observation_id): frame
            for frame in (observation.timeline.frames if observation.timeline else ())
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
        """The first request of the Turn's run, as the Loop recorded what it carries."""
        return self._trace("model.request")

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

    def _carries_content(self) -> bool:
        """The request carries this Turn's input itself: for speech, the observation of the
        sample's STT final; for typed text, the typed observation."""
        request = self._request()
        if request is None:
            return False
        carried = {
            r.get("observation_id")
            for r in self.trace
            if r["stage"] == "model.request_input"
            and r.get("request_id") == request["request_id"]
            and r.get("outcome") == "carried"
        }
        if self.o.task.speech is None:
            return bool(carried)
        final = self._trace("stt.terminal", outcome="final_text")
        return final is not None and final.get("observation_id") in carried

    def _carries_input(self) -> bool:
        request, committed = self._request(), self._trace("turn.committed")
        return (
            request is not None
            and committed is not None
            and request.get("input_id") is not None
            and request.get("input_id") == committed.get("input_id")
        )

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
            what = "transcript" if self.o.task.speech is not None else "typed text"
            lines.append(f"The model request does not carry this Turn's {what}")
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
        stages: list[tuple[str, int | None]] = [("input", self.start)]
        if task.speech is not None:
            stages += [
                ("vad.closed", self._at(self._trace("perception.speech_closed"))),
                ("stt.final", self._at(self._trace("stt.terminal", outcome="final_text"))),
            ]
        stages.append(("turn.committed", self._at(self._trace("turn.committed"))))
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
        ]
        if self.o.audio_output:
            stages.append(("audio.first", self._at(self._output("audio_frame"))))
        stages.append(("outputs.complete", self._completed_at()))
        finished = self._log("run.finished")
        ok = finished is not None and finished.fields.get("state") == "completed"
        stages.append(("run.completed", self._at(finished) if ok else None))
        return stages

    def transcript(self) -> str:
        committed = self._log("input.committed")
        return committed.text if committed is not None and self.o.task.speech else ""

    def sentences(self, transcript: str) -> list[dict[str, Any]]:
        """Each sentence of the spoken prompt, heard in the transcript or not; for one that is
        not, the first layer that lost it, by what each recorded of its sound:

        - ``vad``: no closed speech segment covers its sound;
        - ``stt``: its segment has no final, or a final that leaves it out, as when one
          segment holds it and a sentence that was heard;
        - ``turn``: its own segment's final came, but not into this Turn: rejected for a
          retired segment, or taken by another candidate.

        A sentence's sound is the recording's voiced stretch of that order; where the stretches
        do not match the sentences one to one, every segment is a candidate.
        """
        task, timeline = self.o.task, self.o.timeline
        if task.speech is None or not task.sentences or timeline is None:
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
        rejected = {
            r["segment_id"]
            for r in window
            if r["stage"] == "candidate.transcript_rejected" and "segment_id" in r
        }
        ours = {r["segment_id"] for r in self.trace if "segment_id" in r}

        def covering(index: int) -> list[dict]:
            if not spans:
                return closed
            begin, end = (started + round(at * 1e9) for at in spans[index])
            return [
                r
                for r in closed
                if r.get("start_time_ns", end) < end and r.get("end_time_ns", begin) > begin
            ]

        found = []
        for index, was_heard in enumerate(heard):
            segments = covering(index)
            segment = segments[0] if segments else None
            key = segment["segment_id"] if segment is not None else None
            terminal = terminals.get(key) if key is not None else None
            entry: dict[str, Any] = {
                "index": index + 1,
                "heard": was_heard,
                "span_ms": [round(at * 1000) for at in spans[index]] if spans else None,
                "segment": key[3:15] if key else None,
                "stt": terminal.get("outcome") if terminal is not None else None,
                "text_chars": terminal.get("text_chars") if terminal is not None else None,
                "lost": None,
                "why": None,
            }
            if not was_heard:
                # A segment that also holds a sentence that was heard, or the only one there is.
                shared = any(
                    other != index and heard[other] and segment in covering(other)
                    for other in range(len(heard))
                )
                if segment is None:
                    entry["lost"], entry["why"] = "vad", "no speech segment covered its sound"
                elif terminal is None:
                    entry["lost"], entry["why"] = "stt", "its segment had no STT result"
                elif terminal.get("outcome") != "final_text":
                    why = f"its segment's STT ended {terminal.get('outcome')}"
                    entry["lost"], entry["why"] = "stt", why
                elif shared:
                    why = (
                        f"its segment's STT final ({terminal.get('text_chars')} characters) holds "
                        "another sentence and leaves this one out"
                    )
                    entry["lost"], entry["why"] = "stt", why
                elif key in rejected:
                    why = "its STT final came for a retired segment: the Turn had committed"
                    entry["lost"], entry["why"] = "turn", why
                elif key not in ours:
                    why = "its STT final went to another candidate, not this Turn"
                    entry["lost"], entry["why"] = "turn", why
                else:
                    entry["lost"], entry["why"] = "stt", "its STT final lacks its words"
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

    def _origin(self) -> tuple[str, int | None]:
        if self.o.task.speech is not None:
            return "last voiced sample in", self.start
        return "typed input accepted", self.start

    def metrics(self) -> tuple[Metric, ...]:
        origin = self._origin()
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
                None if self.o.audio_output else "no audio output in this session",
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
                unfinished if self.o.audio_output else "no audio output in this session",
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

    def segments(self) -> tuple[Metric, ...]:
        speech_end = ("last voiced sample in", self.start)
        segments: list[Metric] = []
        if self.o.task.speech is not None:
            closed = self._trace("perception.speech_closed")
            final = self._trace("stt.terminal", outcome="final_text")
            commit = self._trace("stt.commit")
            segments += [
                self._metric(
                    "vad_close",
                    speech_end,
                    ("speech segment closed", self._at(closed)),
                    "input trace",
                ),
                self._metric(
                    "stt_final", speech_end, ("STT final", self._at(final)), "input trace"
                ),
                self._metric(
                    "stt_request_to_final",
                    ("segment committed to STT", self._at(commit)),
                    ("STT final", self._at(final)),
                    "input trace",
                    "the commit queues the segment's request",
                ),
                self._metric(
                    "turn_cutoff",
                    speech_end,
                    ("turn committed", self._at(self._trace("turn.committed"))),
                    "input trace",
                ),
            ]
            if self.o.timeline is not None:
                segments.append(
                    Metric(
                        "input_lateness",
                        round(self.o.timeline.max_lateness_ms, 3),
                        "ms",
                        "frame due",
                        "frame published",
                        "the diagnostic source's cadence, at worst",
                        self.o.timeline.audio_frames,
                    )
                )
        committed_at = self._at(self._trace("turn.committed"))
        request = self._at(self._log("model.started"))
        first_event = self._log("model.first_event")
        kind = first_event.fields.get("event_kind") if first_event is not None else None
        ready = self._log("context.ready")
        wait = ready.fields.get("wait_ms") if ready is not None else None
        held = "how long registered context work held the request back"
        segments += [
            Metric(
                "context_ready_wait",
                round(float(wait), 3) if wait is not None else None,
                "ms",
                "Context asked for the Turn's context",
                "context ready",
                "Context manager log",
                int(wait is not None),
                note=None if wait is None else held,
            ),
            self._metric(
                "cutoff_to_model_request",
                ("turn committed", committed_at),
                ("model request", request),
                "input trace and loop log",
            ),
            *self._request_sent(),
            self._metric(
                "model_first_event",
                ("model request", request),
                ("first model stream event", self._at(first_event)),
                "loop log",
                # Possibly only that the response began: the first text delta says more.
                note=f"its kind: {kind}" if kind else None,
            ),
            self._metric(
                "model_first_text_delta",
                ("model request", request),
                ("first nonempty text delta", self._at(self._log("model.first_text"))),
                "loop log",
                note="the first token, as far as the stream shows it",
            ),
            self._metric(
                "first_displayable_text",
                ("model request", request),
                ("first answer text out", self._at(self._output("text_chunk"))),
                "loop log to the output boundary",
            ),
        ]
        if self.o.audio_output:
            segments += self._speech()
        if self.o.task.screen:
            segments += self._vision(committed_at)
        return tuple(segments)

    def _vision(self, committed_at: int | None) -> list[Metric]:
        encode = (
            [f.encode_ms for f in self.o.timeline.frames if f.kind == "screen"]
            if self.o.timeline
            else []
        )
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

    def _request_sent(self) -> list[Metric]:
        """The model request as its provider sent it: encoding time here, the pictures it
        carries and the body's size. Only providers that log it, the OpenAI Responses one."""
        sent = self._log("model.request_sent")
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
        return found

    def _speech(self) -> list[Metric]:
        output = self._output("audio_frame")
        output_id = output.output_id if output is not None else None
        segment = self._log("speech.segment", output_id=output_id) if output_id else None
        speech = self._log("speech.request", output_id=output_id) if output_id else None
        request_id = speech.fields.get("request_id") if speech is not None else None
        # Only HTTP PCM providers log their first PCM; the Router's request is every plugin's.
        pcm = self._log("tts.first_pcm", request_id=request_id) if request_id else None
        router = "speech synthesis logs"
        return [
            self._metric(
                "tts_text_ready_to_request",
                ("first speakable segment ready", self._at(segment)),
                ("TTS request", self._at(speech)),
                router,
            ),
            self._metric(
                "tts_request_to_first_pcm",
                ("TTS request", self._at(speech)),
                ("first PCM", self._at(pcm)),
                "speech synthesis and TTS logs",
                # Without the request, where the scenario stopped says why.
                None if speech is None else "this TTS plugin logs no first PCM",
            ),
            self._metric(
                "first_pcm_to_first_audio_frame",
                ("first PCM", self._at(pcm)),
                ("first answer audio frame out", self._at(output)),
                "TTS log to the output boundary",
            ),
            self._metric(
                "tts_request_to_first_audio_frame",
                ("TTS request", self._at(speech)),
                ("first answer audio frame out", self._at(output)),
                "speech synthesis log to the output boundary",
            ),
        ]

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
        if self.o.timeline is not None:
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
            key = (
                record.name
                if record.name not in ("speech.segment", "speech.request")
                else f"{record.name}:{record.fields.get('output_id')}"
            )
            if key in seen:
                continue
            seen.add(key)
            detail = {
                k: v
                for k, v in record.fields.items()
                if k in ("state", "reason", "error_type", "event_kind", "segment")
            }
            if turn is not None and record.fields.get("turn_id") == self.o.turn_id:
                detail["turn"] = turn
            for name in ("run_id", "request_id"):
                if record.name.startswith(("model.", "run.")) and record.fields.get(name):
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
