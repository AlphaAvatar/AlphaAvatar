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

Evidence joins by identity: the input trace hashes identities per session, so a Turn's
records are found through ``InputTrace.identity`` and the decision, candidate and segment
identities they share. Selected frames are matched to published ones by perception event
sequence. Every time is ``time.monotonic_ns``; intervals are milliseconds from the response
start: the frame carrying the last voiced sample, or the typed input's acceptance.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .enums import ScenarioOutcome
from .samples import Task
from .schemas import Evidence, Metric, ScenarioResult
from .transport import LogRecord, OutputRecord, SourceTimeline

_EXCERPT = 200
_EVIDENCE = 64
_ASSISTANT = "assistant"


@dataclass(slots=True)
class TurnObservation:
    task: Task
    configuration: str
    start_ns: int | None  # The response start; None when the input never went in
    timeline: SourceTimeline | None
    turn_id: str | None
    records: list[OutputRecord]
    logs: list[LogRecord]
    trace: list[dict[str, Any]]
    identity: Callable[[str], str]
    audio_output: bool
    ended: str | None = None  # timeout, interrupted or session_failed, when not finished
    dropped: int = 0  # Output events the sink lost
    queues: dict[str, Any] = field(default_factory=dict)


def scenario(observation: TurnObservation) -> ScenarioResult:
    turn = _Turn(observation)
    stages = turn.stages()
    blocked = next((name for name, at in stages if at is None), None)
    transcript, answer = turn.transcript(), turn.answer()
    task = observation.task
    details: list[str] = []
    if blocked is None:
        if task.transcript_words and not task.heard(transcript):
            blocked = "stt.final"
            details.append("The transcript does not contain the sample's words")
        elif not task.answered(answer):
            blocked = "answer"
            details.append(f"The answer contains none of: {', '.join(task.answer_words)}")
    if observation.ended is not None:
        details.append(f"Ended by {observation.ended.replace('_', ' ')}")
    if observation.ended == "interrupted" and blocked is not None:
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
        details=tuple(details),
        task=task.prompt,
        transcript=transcript[:_EXCERPT] or None,
        answer=answer[:_EXCERPT] or None,
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
        self.answers = [r for r in self.records if r.lane == _ASSISTANT]
        # Speech and TTS logs carry no Turn: they belong to it through its outputs' requests.
        outputs = {r.output_id for r in self.records}
        requests = {
            r.fields.get("request_id")
            for r in observation.logs
            if r.name == "speech.request" and r.fields.get("output_id") in outputs
        }
        self.logs = [
            r
            for r in observation.logs
            if (turn_id is not None and r.fields.get("turn_id") == turn_id)
            or r.fields.get("output_id") in outputs
            or (r.name.startswith("tts.") and r.fields.get("request_id") in requests)
        ]
        self.trace = self._chain(observation.trace, observation.identity, turn_id)

    # Correlation

    @staticmethod
    def _chain(trace: list[dict], identity: Callable[[str], str], turn_id: str | None) -> list:
        if turn_id is None:
            return []
        key = identity(turn_id)
        turn = [r for r in trace if r.get("turn_id") == key]
        decisions = {r["decision_id"] for r in turn if "decision_id" in r}
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
        ]
        return sorted(chained, key=lambda r: r["trace_sequence"])

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

    def stages(self) -> list[tuple[str, int | None]]:
        task = self.o.task
        stages: list[tuple[str, int | None]] = [("input", self.start)]
        if task.speech is not None:
            stages += [
                ("vad.closed", self._at(self._trace("perception.speech_closed"))),
                ("stt.final", self._at(self._trace("stt.terminal", outcome="final_text"))),
            ]
        committed = self._log("input.committed")
        stages.append(("turn.committed", self._at(committed) if self.o.turn_id else None))
        if task.screen:
            visual = self._trace("context.visual")
            selected = visual is not None and visual.get("frame_count", 0) > 0
            stages.append(("frames.selected", self._at(visual) if selected else None))
        stages += [
            ("model.request", self._at(self._log("model.started"))),
            ("model.first_event", self._at(self._log("model.first_event"))),
            ("text.first", self._at(self._output("text_chunk"))),
            ("text.complete", self._at(self._output("control", control="text_complete"))),
        ]
        if self.o.audio_output:
            stages.append(("audio.first", self._at(self._output("audio_frame"))))
        finished = self._log("run.finished")
        complete = self._output("control", control="complete", last=True)
        ok = finished is not None and finished.fields.get("state") == "completed"
        stages.append(("response.complete", self._at(complete) if ok else None))
        return stages

    def transcript(self) -> str:
        committed = self._log("input.committed")
        return committed.text if committed is not None and self.o.task.speech else ""

    def answer(self) -> str:
        return "".join(r.text for r in self.answers if r.kind == "text_chunk")

    # Metrics

    def _metric(
        self,
        name: str,
        start: tuple[str, int | None],
        end: tuple[str, int | None],
        boundary: str,
        note: str | None = None,
    ) -> Metric:
        value = None
        if start[1] is not None and end[1] is not None:
            value = round((end[1] - start[1]) / 1e6, 3)
        return Metric(name, value, "ms", start[0], end[0], boundary, note=note)

    def _origin(self) -> tuple[str, int | None]:
        if self.o.task.speech is not None:
            return "last voiced sample in", self.start
        return "typed input accepted", self.start

    def metrics(self) -> tuple[Metric, ...]:
        origin = self._origin()
        boundary = "diagnostic input to the output boundary, server side"
        text, audio = self._output("text_chunk"), self._output("audio_frame")
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
                ("text complete", self._at(self._output("control", control="text_complete"))),
                boundary,
            ),
            self._metric(
                "audio_last_frame",
                origin,
                ("last answer audio frame out", self._at(self._output("audio_frame", last=True))),
                boundary,
            ),
            self._metric(
                "response_final",
                origin,
                (
                    "response complete",
                    self._at(self._output("control", control="complete", last=True)),
                ),
                boundary,
            ),
        ]
        selected = self._selected()
        if self.o.task.screen and selected and self.start is not None:
            last = max(frame["published_ns"] for frame in selected)
            arrival = max(last, self.start)
            metrics.append(
                self._metric(
                    "last_required_input",
                    origin,
                    ("last selected frame or voiced sample in", arrival),
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
                len(frames),
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
        committed = self._trace("turn.committed")
        committed_at = self._at(committed) or self._at(self._log("input.committed"))
        request = self._at(self._log("model.started"))
        segments += [
            self._metric(
                "cutoff_to_model_request",
                ("turn committed", committed_at),
                ("model request", request),
                "input trace and loop log",
            ),
            self._metric(
                "model_first_token",
                ("model request", request),
                ("first model event", self._at(self._log("model.first_event"))),
                "loop log",
            ),
            self._metric(
                "model_first_text",
                ("model request", request),
                ("first answer text out", self._at(self._output("text_chunk"))),
                "loop log to the output boundary",
            ),
        ]
        if self.o.audio_output:
            segments += self._speech()
        frames = self._selected()
        if self.o.task.screen:
            encode = (
                [f.encode_ms for f in self.o.timeline.frames if f.kind == "screen"]
                if self.o.timeline
                else []
            )
            segments.append(
                Metric(
                    "frame_input_to_available",
                    round(statistics.median(encode), 3) if encode else None,
                    "ms",
                    "frame arrived",
                    "frame published to perception",
                    "the diagnostic source: JPEG encoding, as the RTC video input",
                    len(encode),
                    note="median",
                )
            )
            ages = [
                f["age_at_request_ms"] for f in frames if f.get("age_at_request_ms") is not None
            ]
            segments.append(
                Metric(
                    "selected_frame_age",
                    round(max(ages), 3) if ages else None,
                    "ms",
                    "frame arrived",
                    "model request",
                    "selected frames, oldest",
                    len(ages),
                    values=tuple(ages),
                )
            )
            published = [f["published_ns"] for f in frames if "published_ns" in f]
            wait = None
            if published and committed_at is not None:
                wait = round(max(0.0, (max(published) - committed_at) / 1e6), 3)
            segments.append(
                Metric(
                    "vision_wait",
                    wait,
                    "ms",
                    "turn committed",
                    "last selected frame in",
                    "the model request's wait for frames after the cutoff",
                    len(published),
                    note="0: every selected frame was in before the cutoff",
                )
            )
        return tuple(segments)

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
                None if pcm is not None else "this TTS plugin logs no first PCM",
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

    def _selected(self) -> list[dict[str, Any]]:
        timeline = self.o.timeline
        if timeline is None:
            return []
        published = {frame.sequence: frame for frame in timeline.frames if frame.kind == "screen"}
        request = self._at(self._log("model.started"))
        selected = []
        for record in self.trace:
            if record["stage"] != "context.frame_selected":
                continue
            frame = published.get(record.get("sequence"))
            item: dict[str, Any] = {
                "sequence": record.get("sequence", 0),
                "matched": frame is not None,
            }
            if frame is not None:
                item["published_ns"] = frame.published_ns
                if self.start is not None:
                    item["offset_from_speech_end_ms"] = round((frame.end_ns - self.start) / 1e6, 3)
                if request is not None:
                    item["age_at_request_ms"] = round((request - frame.end_ns) / 1e6, 3)
            selected.append(item)
        return selected

    def frames(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            {key: value for key, value in frame.items() if key != "published_ns"}
            for frame in self._selected()
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
            for key in ("turn_id", "decision_id", "candidate_id", "segment_id"):
                if key in record:
                    detail[key.removesuffix("_id")] = record[key][3:15]
            items.append((record["recorded_time_ns"], record["stage"], "trace", detail))
        # Outputs and logs carry the raw Turn; the trace's token for it joins them up.
        turn = self.o.identity(self.o.turn_id)[3:15] if self.o.turn_id else None
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
            if record.control or record.playback:
                detail["type"] = record.control or record.playback
            items.append((record.monotonic_ns, f"output.{record.kind}", "output", detail))
        audio = [r for r in self.answers if r.kind == "audio_frame"]
        if audio:
            items.append(
                (audio[-1].monotonic_ns, "output.audio_frame_last", "output", {"lane": _ASSISTANT})
            )
        items.sort(key=lambda item: item[0])
        return tuple(
            Evidence(round((at - self.start) / 1e6, 3), stage, source, detail)
            for at, stage, source, detail in items[:_EVIDENCE]
        )
