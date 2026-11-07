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
"""The diagnostic session's transport: where an RTC backend would carry media.

``DiagnosticSource`` publishes samples as the RTC input adapters publish media: microphone
frames at their own cadence, screen frames at the configured interval. ``DiagnosticSink`` reads the output boundary as an RTC transport does and acts as
the local audio queue, acknowledging playback; it plays to no device. ``LogTimings`` keeps
the timing events the session already logs. Every time is ``time.monotonic_ns``, the
session clock's monotonic part.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import numpy as np

if TYPE_CHECKING:
    from alphaavatar.core.output import OutputRuntime
    from alphaavatar.core.perception import PerceptionRuntime

    from .samples import Speech

_SOURCE = "doctor"


@dataclass(slots=True)
class Frame:
    """One published input frame, as the session received it."""

    kind: str  # audio or screen
    sequence: int  # The perception event sequence
    observation_id: str
    published_ns: int
    end_ns: int  # The observation time the frame carries
    encode_ms: float = 0.0  # Screen frames: JPEG encoding before publication


@dataclass(slots=True)
class SourceTimeline:
    started_ns: int = 0
    voiced_end_ns: int | None = None  # When the frame with the last voiced sample went in
    voiced_end_sequence: int | None = None  # That frame's perception event sequence
    audio_frames: int = 0
    max_lateness_ms: float = 0.0  # Behind the sample cadence, at worst
    frames: list[Frame] = field(default_factory=list)  # Screen frames, and audio milestones


class DiagnosticSource:
    def __init__(
        self,
        perception: PerceptionRuntime,
        *,
        device_id: str,
        frame_ms: int,
        video_interval_sec: float,
    ) -> None:
        self._perception, self._device_id = perception, device_id
        self._frame_ms, self._video_interval = frame_ms, video_interval_sec
        self._sources: list[tuple[Any, Any, Any]] = []

    def _state(self, source, modality, kind, state, reason: str) -> None:
        from alphaavatar.core.perception.schemas import MediaSourceStateEvent

        self._perception.publish_source_state(
            MediaSourceStateEvent(
                source=source,
                modality=modality,
                source_kind=kind,
                state=state,
                device_id=self._device_id,
                reason=reason,
                metadata={"rtc_backend": _SOURCE},
            )
        )

    def start(self, *, audio: bool, screen: bool) -> None:
        from alphaavatar.core.perception.enums import (
            MediaModality,
            MediaSourceKind,
            MediaSourceState as State,
        )

        tracks = [("audio", MediaModality.AUDIO, MediaSourceKind.MICROPHONE)] * audio
        tracks += [("screen", MediaModality.VIDEO, MediaSourceKind.SCREEN)] * screen
        for name, modality, kind in tracks:
            source = self._perception.next_source(f"env:{name}:{self._device_id}:{_SOURCE}")
            self._state(source, modality, kind, State.STARTED, "doctor_sample")
            self._sources.append((source, modality, kind))

    def stop(self) -> None:
        from alphaavatar.core.perception.enums import MediaSourceState as State

        for source, modality, kind in self._sources:
            self._state(source, modality, kind, State.ENDED, "doctor_sample_ended")
        self._sources.clear()

    def _source(self, kind) -> Any:
        return next(source for source, _, source_kind in self._sources if source_kind == kind)

    async def play(
        self,
        speech: Speech,
        picture: np.ndarray | None,
        done: asyncio.Event,
        timeline: SourceTimeline,
    ) -> None:
        """The recording at its cadence, then silence until ``done``; the picture throughout.

        ``timeline`` fills as frames go in, so what was sent survives a cancelled playback.
        """
        timeline.started_ns = time.monotonic_ns()
        tasks = [asyncio.create_task(self._audio(speech, done, timeline), name="doctor_audio")]
        if picture is not None:
            tasks.append(
                asyncio.create_task(self._screen(picture, done, timeline), name="doctor_screen")
            )
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _audio(self, speech: Speech, done: asyncio.Event, timeline: SourceTimeline) -> None:
        from alphaavatar.core.env import EnvObservation
        from alphaavatar.core.media import AudioFrame, AudioFramePayload
        from alphaavatar.core.perception.enums import (
            MediaModality,
            MediaSourceKind,
            MediaSourceState as State,
        )
        from alphaavatar.core.time import RuntimeTimeRange

        from .samples import SAMPLE_RATE

        source = self._source(MediaSourceKind.MICROPHONE)
        samples = SAMPLE_RATE * self._frame_ms // 1000
        size = samples * 2
        voiced_end = int(speech.voiced_end_sec * SAMPLE_RATE) * 2
        period_ns = self._frame_ms * 1_000_000
        index = 0
        active = False
        while index * size < len(speech.pcm) or not done.is_set():
            data = speech.pcm[index * size : (index + 1) * size]
            data += bytes(size - len(data))
            due = timeline.started_ns + (index + 1) * period_ns
            await asyncio.sleep(max(0, due - time.monotonic_ns()) / 1e9)
            ended_at = self._perception.clock.now()
            timeline.max_lateness_ms = max(
                timeline.max_lateness_ms, (ended_at.monotonic_ns - due) / 1e6
            )
            frame = AudioFrame(SAMPLE_RATE, 1, samples, data)
            frame_id = uuid4().hex
            observation = EnvObservation.audio_frame(
                time_range=RuntimeTimeRange(
                    start=ended_at.shifted(-frame.duration_sec), end=ended_at
                ),
                source=source,
                frame_id=frame_id,
                device_id=self._device_id,
                payload=AudioFramePayload.create(frame=frame, frame_id=frame_id),
                metadata={"frame_index": index + 1, "rtc_backend": _SOURCE},
            )
            if not active:
                self._state(
                    source,
                    MediaModality.AUDIO,
                    MediaSourceKind.MICROPHONE,
                    State.ACTIVE,
                    "frame_received",
                )
                active = True
            event = self._perception.publish_observation(observation)
            published = time.monotonic_ns()
            index += 1
            timeline.audio_frames = index
            if index * size >= voiced_end > (index - 1) * size and event is not None:
                timeline.voiced_end_ns, timeline.voiced_end_sequence = published, event.sequence
                timeline.frames.append(
                    Frame(
                        "audio",
                        event.sequence,
                        observation.observation_id,
                        published,
                        ended_at.monotonic_ns,
                    )
                )

    async def _screen(
        self, picture: np.ndarray, done: asyncio.Event, timeline: SourceTimeline
    ) -> None:
        from alphaavatar.core.env import EnvObservation
        from alphaavatar.core.media import VideoFramePayload
        from alphaavatar.core.media.codecs.video import (
            bgr_to_video_frame,
            encode_video_frame_to_jpeg,
        )
        from alphaavatar.core.perception.enums import (
            MediaModality,
            MediaSourceKind,
            MediaSourceState as State,
        )
        from alphaavatar.core.time import RuntimeTimeRange

        source = self._source(MediaSourceKind.SCREEN)
        frame = bgr_to_video_frame(picture)
        period_ns = int(self._video_interval * 1e9)
        index = 0
        while not done.is_set():
            due = timeline.started_ns + index * period_ns
            await asyncio.sleep(max(0, due - time.monotonic_ns()) / 1e9)
            occurred_at = self._perception.clock.now()
            # As the RTC video input: encoded off the loop, published with its arrival time.
            jpeg = await asyncio.to_thread(encode_video_frame_to_jpeg, frame, jpeg_quality=85)
            encoded = time.monotonic_ns()
            frame_id = uuid4().hex
            observation = EnvObservation.screen_frame(
                time_range=RuntimeTimeRange.point(occurred_at),
                source=source,
                frame_id=frame_id,
                device_id=self._device_id,
                payload=VideoFramePayload.create(frame=frame, frame_id=frame_id, jpeg_bytes=jpeg),
                metadata={"frame_index": index + 1, "rtc_backend": _SOURCE},
            )
            if not index:
                self._state(
                    source,
                    MediaModality.VIDEO,
                    MediaSourceKind.SCREEN,
                    State.ACTIVE,
                    "frame_received",
                )
            event = self._perception.publish_observation(observation)
            index += 1
            if event is not None:
                timeline.frames.append(
                    Frame(
                        "screen",
                        event.sequence,
                        observation.observation_id,
                        time.monotonic_ns(),
                        occurred_at.monotonic_ns,
                        (encoded - occurred_at.monotonic_ns) / 1e6,
                    )
                )


@dataclass(slots=True)
class OutputRecord:
    """One event at the output boundary, without audio or private payload bodies."""

    monotonic_ns: int
    kind: str
    lane: str
    turn_id: str | None
    run_id: str | None
    output_id: str | None
    text: str = ""  # Text chunks only, for the task check and a bounded excerpt
    audio_sec: float = 0.0
    control: str | None = None
    reason: str | None = None  # Controls: why, as the producer states it
    playback: str | None = None
    targets: tuple[str, ...] = ()  # The outputs an interruption ends
    request_id: str | None = None  # The model request a model's output came from


@dataclass(slots=True)
class _Queue:
    """A real-time audio queue from the first frame: gaps are where playback would starve."""

    end_ns: int = 0
    underruns: int = 0
    underrun_ms: float = 0.0


class DiagnosticSink:
    _NAME = "doctor.sink"

    def __init__(self, output: OutputRuntime) -> None:
        self._output = output
        self.records: list[OutputRecord] = []
        self.queues: dict[str, _Queue] = {}
        self._subscription = None
        self._task: asyncio.Task[None] | None = None
        self._pushed: dict[str, float] = {}

    @property
    def dropped(self) -> int:
        return self._subscription.dropped_count if self._subscription is not None else 0

    async def start(self) -> None:
        self._subscription = await self._output.stream.subscribe(self._NAME, max_pending=4096)
        self._task = asyncio.create_task(self._run(), name="doctor_sink")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        await self._output.stream.unsubscribe(self._NAME)

    async def _receipt(self, identity, kind) -> None:
        from alphaavatar.core.env import EnvOutput
        from alphaavatar.core.output.enums import OutputKind
        from alphaavatar.core.output.schemas import OutputPlayback, OutputSource

        pushed = self._pushed.get(identity.output_id, 0.0)
        await self._output.publish(
            EnvOutput(
                kind=OutputKind.PLAYBACK,
                lane=identity.lane,
                scope=identity.scope,
                source=OutputSource(_SOURCE),
                output_id=identity.output_id,
                payload=OutputPlayback(kind, pushed, pushed, 0.0),
                metadata={"transport": _SOURCE, "measurement": "local_audio_queue"},
            )
        )

    async def _run(self) -> None:
        from alphaavatar.core.output.enums import OutputControlType, OutputKind, OutputPlaybackType

        while True:
            event = await self._subscription.get()
            output = event.output
            payload, now = output.payload, event.monotonic_ns
            record = OutputRecord(
                now,
                output.kind.value,
                output.lane.value,
                output.scope.turn_id if output.scope is not None else None,
                output.scope.run_id if output.scope is not None else None,
                output.output_id,
                request_id=output.source.request_id if output.source is not None else None,
            )
            self.records.append(record)
            if output.kind == OutputKind.TEXT_CHUNK:
                record.text = payload.text[:4096]
            elif output.kind == OutputKind.PLAYBACK:
                record.playback = payload.type.value
            elif output.kind == OutputKind.AUDIO_FRAME:
                record.audio_sec = payload.duration_sec
                queue = self.queues.setdefault(output.output_id, _Queue(end_ns=now))
                if now > queue.end_ns:
                    queue.underruns += queue.end_ns != now
                    queue.underrun_ms += (now - queue.end_ns) / 1e6
                queue.end_ns = max(queue.end_ns, now) + int(payload.duration_sec * 1e9)
                if self._output.can_deliver(output.output_id):
                    first = output.output_id not in self._pushed
                    self._pushed[output.output_id] = (
                        self._pushed.get(output.output_id, 0.0) + payload.duration_sec
                    )
                    kind = OutputPlaybackType.STARTED if first else OutputPlaybackType.PROGRESS
                    await self._receipt(self._output.output_identity(output.output_id), kind)
            elif output.kind == OutputKind.CONTROL:
                record.control, record.reason = payload.type.value, payload.reason
                if payload.type == OutputControlType.INTERRUPT:
                    record.targets = tuple(identity.output_id for identity in payload.targets)
                    for identity in payload.targets:
                        await self._receipt(identity, OutputPlaybackType.INTERRUPTED)
                elif payload.type == OutputControlType.COMPLETE:
                    identity = self._output.output_identity(output.output_id)
                    if identity is not None and output.output_id in self._pushed:
                        await self._receipt(identity, OutputPlaybackType.FINISHED)


@dataclass(frozen=True, slots=True)
class LogRecord:
    monotonic_ns: int
    name: str
    fields: dict[str, Any]
    text: str = ""  # input.committed only: the committed transcript, kept in memory


class LogTimings(logging.Handler):
    """Timing events the session already logs, stamped when they are emitted.

    Structured events carry their fields. The speech synthesis and TTS stages are debug
    messages; they are matched by their fixed beginning, and their arguments by position.
    """

    _EVENTS = frozenset(
        (
            "input.committed",
            "model.started",
            "model.first_event",
            "model.first_text",
            "model.request_sent",
            "run.finished",
        )
    )
    _MESSAGES = {
        "SPEECH SEGMENT output_id=": ("speech.segment", ("output_id", "segment")),
        "SPEECH REQUEST output_id=": ("speech.request", ("output_id", "segment", "request_id")),
        "TTS FIRST PCM provider=": ("tts.first_pcm", ("provider", "request_id", "attempt")),
        "Speech first audio output_id=": ("speech.first_audio", ("output_id", "segment")),
        "Context readiness turn_id=": ("context.ready", ("turn_id", "ready", "wait_ms")),
        "INFERENCE SUMMARY method=": (
            "inference.summary",
            (
                "method",
                "pid",
                "calls",
                "window_seconds",
                "queue_avg_ms",
                "queue_max_ms",
                "execution_avg_ms",
                "execution_max_ms",
            ),
        ),
    }

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[LogRecord] = []
        self._logger = logging.getLogger("alphaavatar")
        self._level = self._logger.level

    def __enter__(self) -> LogTimings:
        self._logger.addHandler(self)
        self._logger.setLevel(logging.DEBUG)
        return self

    def __exit__(self, *exc: object) -> None:
        self._logger.removeHandler(self)
        self._logger.setLevel(self._level)

    def emit(self, record: logging.LogRecord) -> None:
        from alphaavatar.core.log.events import ConversationEvent

        now, message = time.monotonic_ns(), record.msg
        if isinstance(message, ConversationEvent):
            if message.name in self._EVENTS:
                text = "\n".join(message.parts) if message.name == "input.committed" else ""
                self.records.append(LogRecord(now, message.name, dict(message.fields), text))
        elif isinstance(message, str) and isinstance(record.args, tuple):
            for prefix, (name, keys) in self._MESSAGES.items():
                if message.startswith(prefix):
                    fields = dict(zip(keys, record.args, strict=False))
                    self.records.append(LogRecord(now, name, fields))
                    break
