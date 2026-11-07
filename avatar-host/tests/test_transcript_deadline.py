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
"""A transcript that misses its deadline, on the configured chain (KD-17).

The configuration is loaded and the session assembled as start assembles it: the Router from
its own factory, which gives turn taking the segment STT's fallback notice, the segment STT
itself, Context, Loop and Engine, at their default deadlines. Stand-ins: the transcription
service (a loopback endpoint that answers each request after its delay), the VAD (speech
published as Audio Activity publishes it), the turn-taking endpoint model, the model provider
(it records each request), the TTS (silence, at real time) and Memory and Persona (empty).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from unittest import mock

import doctor_doubles as doubles
import pytest

from alphaavatar.agents.avatar.provider.schemas import ModelInputMessage, ModelTextPart
from alphaavatar.agents.router.enums import TurnTakingMode
from alphaavatar.agents.router.models import TurnTakingModelBase, TurnTakingModelCapabilities
from alphaavatar.agents.router.schemas import TurnTakingAssessment, TurnTakingEvidence
from alphaavatar.agents.runtime.inference.protocol import INFERENCE_ENDPOINT_ENV
from alphaavatar.agents.runtime.plugin import AvatarModule, resolution
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.env.schemas import (
    PerceptionEntityRef,
    PerceptionSegmentRef,
    PerceptionSourceRef,
)
from alphaavatar.core.media import AudioFrame, AudioFramePayload
from alphaavatar.core.output.enums import OutputLane
from alphaavatar.core.output.schemas import OutputTranscriptChunk
from alphaavatar.core.output.stream import OutputSubscription
from alphaavatar.host.application.bootstrap import create_execution
from alphaavatar.host.configs import load_application
from alphaavatar.host.doctor.transport import DiagnosticSink
from alphaavatar.host.execution.execution import HostExecution
from alphaavatar.host.sessions.schemas import SessionContext
from alphaavatar.plugins.router.processors.turn_taking import processor as turn_taking

HANG_GUARD = 20
WAIT, DEADLINE = 0.75, 3.0  # Turn taking's transcript wait and hard deadline, by default
LATE = 4.5  # A final past the deadline
DEVICE = "microphone-device"
SPEECH = "router:speech:microphone"  # Audio Activity's speech source of the microphone
MICROPHONE = {"source_id": "microphone", "source_generation": 1}
NOTICE = '<system_notice code="voice.transcription_unavailable" current="true">'
REPEAT = "Briefly and naturally ask them to repeat what they said."
SUM, CARD, LOST = "What is two plus three?", "What color is the card?", "Words too late."


class Transcriber:
    """The transcription service on loopback: request by request, its words after its delay."""

    def __init__(self, *answers: tuple[float, str]) -> None:
        self.answers = list(answers)

    async def __call__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while True:
            try:
                head = await reader.readuntil(b"\r\n\r\n")
            except asyncio.IncompleteReadError:  # The client closed the connection.
                break
            await reader.readexactly(int(re.search(rb"(?i)content-length: *(\d+)", head)[1]))
            delay, words = self.answers.pop(0)
            await asyncio.sleep(delay)
            events = ({"type": "transcript.text.done", "text": words}, "[DONE]")
            body = "".join(
                f"data: {e if isinstance(e, str) else json.dumps(e)}\n\n" for e in events
            )
            head = "HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\n"
            writer.write(f"{head}content-length: {len(body)}\r\n\r\n{body}".encode())
            await writer.drain()
        writer.close()


class EndpointModel(TurnTakingModelBase):
    """Each complete candidate ends its turn, but one whose last segment ``continues``."""

    def __init__(self, continues: frozenset[str] = frozenset()) -> None:
        self.continues = continues

    @property
    def name(self) -> str:
        return "endpoint stand-in"

    @property
    def capabilities(self) -> TurnTakingModelCapabilities:
        return TurnTakingModelCapabilities(
            modes=frozenset({TurnTakingMode.AUDIO_ONLY}), uses_transcript=True
        )

    async def assess(self, evidence: TurnTakingEvidence) -> TurnTakingAssessment:
        return TurnTakingAssessment(
            turn_candidate_id=evidence.turn_candidate_id,
            candidate_revision=evidence.candidate_revision,
            turn_mode=evidence.turn_mode,
            confidence=1.0,
            end_of_turn_probability=float(evidence.segments[-1].segment_id not in self.continues),
        )


class Recorder(doubles.ScriptedLLM):
    """The model provider: each request's messages, (role, text), recorded as it is sent, and
    when."""

    def __init__(self, files: Path) -> None:
        super().__init__(files)
        self.requests: list[list[tuple[str, str]]] = []
        self.sent: list[float] = []

    @asynccontextmanager
    async def stream(self, request) -> AsyncIterator[AsyncIterator[object]]:
        self.sent.append(time.monotonic())
        self.requests.append(
            [
                (
                    item.role.value,
                    " ".join(p.text for p in item.parts if isinstance(p, ModelTextPart)),
                )
                for item in request.input.items
                if isinstance(item, ModelInputMessage)
            ]
        )
        async with super().stream(request) as events:
            yield events


async def wait_until(condition: Callable[[], object], failure: str) -> None:
    try:
        async with asyncio.timeout(HANG_GUARD):
            while not condition():
                await asyncio.sleep(0.005)
    except TimeoutError:
        pytest.fail(failure, pytrace=False)


@dataclass
class Chain:
    """The started session, the model's requests, its outputs and the one speech source
    Audio Activity routes the microphone's speech through."""

    execution: HostExecution
    model: Recorder
    sink: DiagnosticSink
    speech: PerceptionSourceRef
    finals: set[str] = field(default_factory=set)  # Answers whose transcript's final went out

    async def watch(self, subscription: OutputSubscription) -> None:
        while True:
            output = (await subscription.get()).output
            final = isinstance(output.payload, OutputTranscriptChunk) and output.payload.is_final
            if final and output.lane == OutputLane.ASSISTANT:
                self.finals.add(output.output_id)

    def say(self, segment_id: str, speaker: PerceptionEntityRef | None = None) -> None:
        """Half a second of an utterance as Audio Activity publishes it, then its end; the
        microphone's frames name no ``speaker``."""
        perception, clock = self.execution.runtime.perception, self.execution.runtime.clock
        segment = PerceptionSegmentRef(self.speech, segment_id)
        for index in range(1, 51):
            metadata = {"route_index": index, "input_source": MICROPHONE}
            if index == 1:
                metadata["speech_event"] = "start"
            frame = AudioFramePayload.create(
                frame=AudioFrame(16_000, 1, 160, bytes(320)), frame_id=None
            )
            perception.publish_observation(
                EnvObservation.speech_frame(
                    time_range=clock.point(),
                    source=self.speech,
                    segment=segment,
                    device_id=DEVICE,
                    entity=speaker,
                    payload=frame,
                    metadata=metadata,
                )
            )
        perception.publish_observation(
            EnvObservation.speech_segment(
                time_range=clock.point(),
                source=self.speech,
                segment=segment,
                device_id=DEVICE,
                entity=speaker,
                metadata={"speech_event": "end", "input_source": MICROPHONE},
            )
        )

    def completed(self) -> int:
        """Answers delivered to their transcript's final: nothing of them still goes out."""
        return len(self.finals)

    def records(self, stage: str) -> list[dict]:
        trace = self.execution.runtime.perception.input_trace
        return [r for r in trace.snapshot().to_dict()["records"] if r["stage"] == stage]

    def decided(self) -> list[tuple[str, int]]:
        """Each commit or cancel: its action and how many of its transcripts were missing."""
        found = self.records("candidate.decision")
        return [
            (r["action"], r["missing_count"]) for r in found if r["action"] in ("commit", "cancel")
        ]

    def current(self, request: int) -> str:
        """The request's latest user message: this Turn's input."""
        *_, (role, text) = self.model.requests[request]
        assert role == "user"
        return text

    def history(self, request: int) -> str:
        """The messages before it, the system's left out: earlier Turns as Context replays them."""
        return " ".join(text for role, text in self.model.requests[request][1:-1])


@pytest.fixture
async def session(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    owned_endpoints: set[object],
) -> AsyncIterator[Chain]:
    """The configured session, started; the parameter is (answers, continues): how its
    transcription service answers, request by request, and the segments the endpoint model
    holds."""
    answers, continues = request.param
    server = await asyncio.start_server(Transcriber(*answers), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    owned_endpoints.add(("127.0.0.1", port))
    model = Recorder(tmp_path)
    for module, name, create in (
        (AvatarModule.PROVIDER_LLM, "scripted", lambda: model),
        (AvatarModule.MEMORY, "doctor", doubles.NullMemory),
        (AvatarModule.PERSONA, "doctor", doubles.NullPersona),
        (AvatarModule.VOICE_TTS, "openai", lambda: doubles.ScriptedTTS(frames=12)),
    ):
        monkeypatch.setitem(
            resolution._resolved, (module, name), doubles.stand_in(module, name, create)
        )
    monkeypatch.setattr(
        turn_taking,
        "create_turn_taking_model",
        lambda name, inference_executor: EndpointModel(continues),
    )
    path = tmp_path / "avatar.json"
    path.write_text(
        json.dumps(
            {
                "application": {"home": str(tmp_path / "home")},
                "avatar": {"id": "kd17", "name": "Alpha"},
                "loop": {
                    "plugin": "realtime",
                    "init_config": {
                        "model": {"backend": "scripted", "provider": "openai", "model": "m"}
                    },
                },
                "voice": {
                    "vad": {"plugin": None},
                    "stt": {
                        "plugin": "openai_segment",
                        "model": "gpt-4o-transcribe",
                        "base_url": f"http://127.0.0.1:{port}/v1",
                    },
                    "tts": {"plugin": "openai", "model": "m", "speaker": "ash"},
                },
                "vision": {"enabled": False},
                "router": {
                    "init_config": {
                        "addressing": {"semantic": {"enabled": False}, "visual": {"enabled": False}}
                    }
                },
                "status": {"enabled": False},
                "tools": {
                    "deepresearch": {"plugin": None},
                    "rag": {"plugin": None},
                    "mcp": {"enabled": False},
                },
                "memory": {"plugin": "doctor"},
                "persona": {"plugin": "doctor"},
            }
        )
    )
    environ = {
        "OPENAI_API_KEY": "sk-fictional",
        INFERENCE_ENDPOINT_ENV: str(tmp_path / "unused.sock"),
    }
    try:
        with mock.patch.dict(os.environ, environ):
            config = load_application(path)
            access = SessionContext(DEVICE, "avatar-device", "kd17", {"session_id": "kd17"})
            execution = await create_execution(config, access)
            output = execution.runtime.output
            sink, watching = DiagnosticSink(output), None
            try:
                await sink.start()
                chain = Chain(
                    execution, model, sink, execution.runtime.perception.next_source(SPEECH)
                )
                finals = await output.stream.subscribe("kd17.finals", max_pending=4096)
                watching = asyncio.create_task(chain.watch(finals), name="kd17_finals")
                await execution.start()
                execution.engine.notify_ready()
                yield chain
            finally:
                if watching is not None:
                    watching.cancel()
                    await asyncio.gather(watching, return_exceptions=True)
                    await output.stream.unsubscribe("kd17.finals")
                await sink.stop()
                await execution.aclose()
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.parametrize(
    "session", [(((1.5, SUM), (LATE, LOST), (0.3, CARD)), frozenset())], indirect=True
)
async def test_a_transcript_past_its_deadline_commits_the_notice_and_its_late_final_joins_nothing(
    session: Chain,
) -> None:
    # Later than the transcript wait's point of observation, within the deadline: its words.
    said = time.monotonic()
    session.say("segment-1")
    await wait_until(lambda: session.completed() == 1, "the first turn never completed")
    assert SUM in session.current(0) and "system_notice" not in session.current(0)
    assert WAIT < session.model.sent[0] - said < DEADLINE

    # Past the deadline: the turn commits the STT's notice, so the answer can ask again.
    said = time.monotonic()
    session.say("segment-2")
    await wait_until(
        lambda: len(session.model.requests) == 2, "the untranscribed turn never committed"
    )
    assert NOTICE in session.current(1) and REPEAT in session.current(1)
    assert DEADLINE <= session.model.sent[1] - said < LATE  # At the deadline, not the final
    await wait_until(lambda: session.completed() == 2, "the notice's turn never completed")

    # The next utterance, its request queued behind the late one: that final arrives while the
    # next Turn waits for its own, and joins nothing.
    session.say("segment-3")
    await wait_until(lambda: session.completed() == 3, "the next turn never completed")
    assert CARD in session.current(2) and "system_notice" not in session.current(2)
    assert SUM in session.history(2) and NOTICE in session.history(2)
    assert not any(LOST in text for request in session.model.requests for _, text in request)
    (rejected,) = session.records("candidate.transcript_rejected")
    assert rejected["reason"] == "retired_segment"
    assert session.decided() == [("commit", 0), ("commit", 1), ("commit", 0)]


TWO_SEGMENTS = (((0.3, SUM), (LATE, LOST), (0.3, CARD)), frozenset({"segment-a"}))


@pytest.mark.parametrize("session", [TWO_SEGMENTS], indirect=True)
async def test_a_speakers_turn_keeps_the_words_it_has_and_marks_the_segment_it_lost(
    session: Chain,
) -> None:
    # A turn of two segments: its speech names its speaker, else each segment is its own.
    voice = PerceptionEntityRef("voice-1")
    session.say("segment-a", voice)  # It holds: the speaker goes on.
    session.say("segment-b", voice)
    await wait_until(lambda: session.completed() == 1, "the turn never completed")
    partial = '<unavailable_speech segment_id="segment-b" position="2" />'
    assert SUM in session.current(0) and partial in session.current(0)
    assert "Part of this input could not be understood." in session.current(0)

    session.say("segment-c", voice)
    await wait_until(lambda: session.completed() == 2, "the next turn never completed")
    assert CARD in session.current(1) and "system_notice" not in session.current(1)
    assert SUM in session.history(1) and partial in session.history(1)
    assert not any(LOST in text for request in session.model.requests for _, text in request)
    assert session.decided() == [("commit", 1), ("commit", 0)]


@pytest.mark.parametrize("session", [TWO_SEGMENTS], indirect=True)
async def test_segments_of_no_named_speaker_are_turns_of_their_own_the_lost_one_its_notice(
    session: Chain,
) -> None:
    # The microphone's speech names no speaker: the second segment is a Turn of its own, so
    # the first is answered and the lost one is the notice's Turn, after its deadline.
    session.say("segment-a")
    session.say("segment-b")
    await wait_until(lambda: session.completed() == 2, "the two turns never completed")
    assert SUM in session.current(0) and "system_notice" not in session.current(0)
    assert NOTICE in session.current(1) and REPEAT in session.current(1)
    assert SUM in session.history(1)
    assert not any(LOST in text for request in session.model.requests for _, text in request)
    assert session.decided() == [("commit", 0), ("commit", 1)]
