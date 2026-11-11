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
"""Controlled stand-ins for Doctor's diagnostic session: no model file and no network.

Only the external services and the model files are replaced. Router, Context, Loop, Engine,
output runtime and the shared inference runtime around them are production code. The session
runs in Doctor's diagnostic process, so ``child`` takes the place of that process's entry:
it denies the network as the test process does, installs the stand-ins the test describes in
``DOCTOR_DOUBLES`` (JSON), then runs the real entry. What the stand-ins saw is written to the
test's ``files`` directory. Runners are spawned by name, so they live here, on pytest's
pythonpath.
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib
import json
import logging
import os
import socket
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np

from alphaavatar.agents.avatar.provider.base import StreamingLLMBase
from alphaavatar.agents.avatar.provider.enums import ModelFinishReason, ModelRole
from alphaavatar.agents.avatar.provider.errors import ModelCapabilityError, ModelRequestError
from alphaavatar.agents.avatar.provider.schemas import (
    ModelImagePart,
    ModelInputMessage,
    ModelTextPart,
)
from alphaavatar.agents.avatar.provider.schemas.stream import (
    ModelItemCompleted,
    ModelResponseCompleted,
    ModelTextDelta,
)
from alphaavatar.agents.avatar.voice import (
    STTBase,
    STTCapabilities,
    STTInputMode,
    STTStreamBase,
    TranscriptionEvent,
    TranscriptionEventType,
    TTSBase,
    TTSStreamBase,
)
from alphaavatar.agents.memory.base import MemoryBase
from alphaavatar.agents.persona.base import PersonaBase
from alphaavatar.agents.runtime.capability.registry import AvatarCapabilityRegistry
from alphaavatar.agents.runtime.inference.runner import InferenceRunner
from alphaavatar.agents.runtime.plugin import (
    AvatarModule,
    AvatarModulePlugin,
    ResolvedPlugin,
    resolution,
)
from alphaavatar.core.log.events import log_event
from alphaavatar.core.media import AudioFrame

SPEC = "DOCTOR_DOUBLES"
_logger = logging.getLogger("alphaavatar.plugins.provider.doctor")
TTS_RATE = 24_000
TTS_FRAME = TTS_RATE // 50  # 20 ms
ANSWERS = {"card": "Green.", "sum": "5.", "blind": "I cannot tell."}


class SpeechRunner(InferenceRunner):
    """Silero's request and response layout: a loud window is speech, the state passes on."""

    INFERENCE_METHOD = "alphaavatar.voice.vad.silero"
    REPLICABLE = True

    def initialize(self) -> None:
        if json.loads(os.environ.get(SPEC, "{}")).get("stdout"):
            print("stand-in VAD runner started", flush=True)  # Not for the report.

    def run(self, data: bytes) -> bytes | None:
        values = np.frombuffer(data, dtype=np.float32)
        if values.size != 512 + 64 + 256:
            raise ValueError("Invalid Silero request size")
        response = np.empty(257, dtype=np.float32)
        response[0] = float(np.abs(values[:512]).mean() > 0.02)
        response[1:] = values[576:]
        return response.tobytes()


class TurnTakingRunner(InferenceRunner):
    """Smart Turn's layout: every assessed window ends its turn."""

    INFERENCE_METHOD = "alphaavatar.router.turn_taking.smart_turn_v3"
    REPLICABLE = True

    def run(self, data: bytes) -> bytes | None:
        return np.asarray([1.0], dtype=np.float32).tobytes()


class CachedModelRunner(TurnTakingRunner):
    """Smart Turn's layout, its weights a file in the configured model cache: loaded when it
    is there, fetched into it when it is not, as start fetches a missing model, unless this
    machine switches downloads off; with ``refetch``, fetched again over the one there. Each
    start says which in the test's ``model.log``."""

    WEIGHTS = 64_000  # Bytes a fetch adds to the cache

    def initialize(self) -> None:
        from alphaavatar.agents.utils.files.model.model_files import ModelNotCached, models_offline

        spec = json.loads(os.environ[SPEC])
        files = Path(spec["files"])
        target = Path(self.launch.models_dir) / "doctor" / "weights.bin"
        if target.is_file() and not spec.get("refetch"):
            fetched = "cache"
        elif models_offline():
            raise ModelNotCached("The turn-taking model is not in the cache")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bytes(self.WEIGHTS))
            fetched = "download"
        with (files / "model.log").open("a") as log:
            log.write(f"{fetched}\n")


class MissingFileRunner(TurnTakingRunner):
    """Smart Turn's layout, reading a file its own settings name, which is not there: a missing
    file that no model download would bring."""

    def initialize(self) -> None:
        raise FileNotFoundError("Turn-taking thresholds file not found: /nowhere/thresholds.json")


class StuckRunner(InferenceRunner):
    """A runner whose start never finishes on its own: a model load that hangs. Its process
    names itself in the test's ``files``, so the test can see that it went."""

    INFERENCE_METHOD = "test.doctor.stuck"

    def initialize(self) -> None:
        import time

        if SPEC in os.environ:
            files = Path(json.loads(os.environ[SPEC])["files"])
            (files / "stuck").write_text(str(os.getpid()))
        time.sleep(60)


class MissingModelRunner(InferenceRunner):
    """A runner only vision needs, whose model is not in the cache."""

    INFERENCE_METHOD = "test.doctor.face"

    def initialize(self) -> None:
        raise FileNotFoundError("The face model is not in the cache")


class ScriptedLLM(StreamingLLMBase):
    """Answers from what the request carries: a picture means it can see the card.

    ``images`` False refuses images, as a model without vision input does; ``error`` names a
    request failure to raise instead, such as rejected credentials, or ``capability`` for a
    capability the backend lacks that is not about images. ``messages`` above one
    precedes the card's answer with remarks, each an output of its own. Each request is
    logged as sent, as the OpenAI Responses provider logs it, ``attempts`` times, each
    ``retry`` seconds apart; ``attempts`` 0 logs none, as a provider that logs nothing.
    """

    def __init__(
        self,
        files: Path,
        *,
        images: bool = True,
        answers: dict[str, str] | None = None,
        messages: int = 1,
        error: str | None = None,
        attempts: int = 1,
        retry: float = 0.03,
    ) -> None:
        self.files, self.images, self.messages, self.error = files, images, messages, error
        self.answers = ANSWERS | (answers or {})
        self.attempts, self.retry = attempts, retry

    def validate_input(self, *, require_input_adapter: bool = False) -> None:
        pass

    async def ainvoke_structured(self, model_input, *, output_schema, include_raw=False):
        raise NotImplementedError

    async def aclose(self) -> None:
        pass

    @asynccontextmanager
    async def stream(self, request) -> AsyncIterator[AsyncIterator[object]]:
        parts = [
            part
            for item in request.input.items
            if isinstance(item, ModelInputMessage)
            for part in item.parts
        ]
        text = " ".join(part.text for part in parts if isinstance(part, ModelTextPart)).lower()
        images = [part for part in parts if isinstance(part, ModelImagePart)]
        seen = {
            "images": [part.observation.observation_id for part in images],
            "card": "color is the card" in text,
            "sum": "two plus three" in text,
        }
        with (self.files / "requests.jsonl").open("a") as stream:
            stream.write(json.dumps(seen) + "\n")
        for attempt in range(1, self.attempts + 1):
            if attempt > 1:
                await asyncio.sleep(self.retry)  # The first attempt failed in transit.
            log_event(
                _logger,
                "model.request_sent",
                request_id=request.request_id,
                encode_ms=0.25,
                frame_count=len(images),
                request_bytes=20_000 + 11_000 * len(images),
                attempt=attempt,
            )
        if self.error == "capability":
            raise ModelCapabilityError("This backend cannot represent strict tool schemas")
        if self.error is not None:
            raise ModelRequestError("The provider rejected the credentials", code=self.error)
        if images and not self.images:
            raise ModelCapabilityError("This model accepts no image input", code="image_input")
        if "plus" in text:
            answer = self.answers["sum"]
        elif images:
            answer = self.answers["card"]
        else:
            answer = self.answers["blind"]
        remarks = range(1, self.messages if answer == self.answers["card"] else 1)
        said = [f"Remark {index}." for index in remarks] + [answer]

        async def events() -> AsyncIterator[object]:
            response = f"response:{request.request_id}"
            messages = [
                ModelInputMessage(
                    id=f"answer:{request.request_id}:{index}",
                    role=ModelRole.ASSISTANT,
                    parts=(ModelTextPart(words),),
                )
                for index, words in enumerate(said)
            ]
            # The stream opens with an empty delta: its first event comes before its first text.
            yield ModelTextDelta(
                request_id=request.request_id,
                response_id=response,
                item_id=messages[0].id,
                output_index=0,
                content_index=0,
                text="",
            )
            await asyncio.sleep(0.05)
            for index, message in enumerate(messages):
                words = message.parts[0].text.split(" ")
                for position, word in enumerate(words):
                    yield ModelTextDelta(
                        request_id=request.request_id,
                        response_id=response,
                        item_id=message.id,
                        output_index=index,
                        content_index=0,
                        text=word if not position else f" {word}",
                    )
                yield ModelItemCompleted(
                    request_id=request.request_id,
                    response_id=response,
                    output_index=index,
                    item=message,
                )
            yield ModelResponseCompleted(
                request_id=request.request_id,
                response_id=response,
                items=tuple(messages),
                finish_reason=ModelFinishReason.STOP,
            )

        yield events()


class ScriptedSTTStream(STTStreamBase):
    def __init__(self, stt: ScriptedSTT, source_id: str) -> None:
        self._stt, self.source_id = stt, source_id
        self._events: asyncio.Queue[TranscriptionEvent | None] = asyncio.Queue()

    def push_frame(self, frame: AudioFrame, *, segment_id: str) -> bool:
        return True

    def commit_segment(self, segment_id: str) -> bool:
        if self._stt.chatty:
            print(f"stand-in STT committed {segment_id}", flush=True)  # Not for the report.
        text = self._stt.transcripts.pop(0) if self._stt.transcripts else ""
        with (self._stt.files / "committed").open("a") as stream:
            stream.write(f"{segment_id}\n")  # The test waits on this to interrupt mid-turn.
        loop = asyncio.get_running_loop()
        loop.call_later(
            0.05,
            self._events.put_nowait,
            TranscriptionEvent(
                TranscriptionEventType.FINAL_TRANSCRIPT, self.source_id, segment_id, text
            ),
        )
        return True

    def flush(self) -> bool:
        return True

    def end_input(self) -> bool:
        self._events.put_nowait(None)
        return True

    async def _iterate(self) -> AsyncIterator[TranscriptionEvent]:
        while (event := await self._events.get()) is not None:
            yield event

    def __aiter__(self) -> AsyncIterator[TranscriptionEvent]:
        return self._iterate()

    async def aclose(self) -> None:
        self._events.put_nowait(None)


class ScriptedSTT(STTBase):
    """Segment STT: each committed segment's final is the next scripted transcript."""

    def __init__(self, transcripts: list[str], files: Path, *, chatty: bool = False) -> None:
        self.transcripts, self.files, self.chatty = transcripts, files, chatty

    @property
    def provider(self) -> str:
        return "scripted"

    @property
    def model(self) -> str:
        return "scripted"

    @property
    def capabilities(self) -> STTCapabilities:
        return STTCapabilities(STTInputMode.SEGMENT, False, False)

    def stream(self, *, source_id: str) -> ScriptedSTTStream:
        return ScriptedSTTStream(self, source_id)


class ScriptedTTSStream(TTSStreamBase):
    def __init__(self, text: str, index: int, frames: int | None, fail_after: int | None) -> None:
        self.request_id = f"tts-{index}"
        self._frames = max(12, len(text) // 2) if frames is None else frames
        self._fail_after = fail_after

    async def __anext__(self) -> AudioFrame:
        if self._fail_after is not None and not self._fail_after:
            raise RuntimeError("Scripted TTS failed mid-stream")
        if not self._frames:
            raise StopAsyncIteration
        self._frames -= 1
        if self._fail_after is not None:
            self._fail_after -= 1
        # At real time: audio goes on well after the model's run has finished.
        await asyncio.sleep(0.02)
        return AudioFrame(TTS_RATE, 1, TTS_FRAME, b"\x10\x00" * TTS_FRAME)

    async def aclose(self) -> None:
        self._frames = 0


class ScriptedTTS(TTSBase):
    """``fail`` refuses every request; ``fail_after`` maps a request's number, from 1, to the
    frames it yields before failing."""

    def __init__(
        self,
        *,
        frames: int | None = None,
        fail: bool = False,
        fail_after: dict[str, int] | None = None,
    ) -> None:
        self.frames, self.fail, self.requests = frames, fail, 0
        self.fail_after = fail_after or {}

    @property
    def sample_rate(self) -> int:
        return TTS_RATE

    @property
    def num_channels(self) -> int:
        return 1

    def synthesize(self, text: str) -> ScriptedTTSStream:
        if self.fail:
            raise RuntimeError("Scripted TTS is unavailable")
        self.requests += 1
        after = self.fail_after.get(str(self.requests))
        return ScriptedTTSStream(text, self.requests, self.frames, after)

    async def aclose(self) -> None:
        pass


class NullMemory(MemoryBase):
    """No recall and no persistence: the session runs without Memory's services."""

    def __init__(self, **_: object) -> None:
        self._registry = AvatarCapabilityRegistry()

    @property
    def capability_registry(self) -> AvatarCapabilityRegistry:
        return self._registry

    @property
    def root_context_id(self) -> str:
        return "doctor"

    @property
    def memory_content(self) -> str:
        return ""

    def content_for(self, snapshot) -> str:
        return ""

    async def on_start(self) -> None:
        pass

    async def on_stop(self) -> None:
        pass


class NullPersona(PersonaBase):
    """No profiles and no persistence: the session runs without Persona's services."""

    def __init__(self, **_: object) -> None:
        self._registry = AvatarCapabilityRegistry()

    @property
    def capability_registry(self) -> AvatarCapabilityRegistry:
        return self._registry

    @property
    def persona_cache(self) -> dict:
        return {}

    @property
    def persona_content(self) -> str:
        return ""

    def content_for(self, snapshot) -> str:
        return ""

    def cache_for(self, participant_id: str):
        return None

    async def load_profile(self, *, participant_id: str) -> None:
        pass

    async def save(self, *, user_id: str | None = None) -> None:
        pass

    async def on_start(self) -> None:
        pass

    async def on_stop(self) -> None:
        pass


# The diagnostic process


class _Factory(AvatarModulePlugin):
    def __init__(self, create, runners=lambda config: ()) -> None:
        super().__init__("doctor doubles", "0", "tests")
        self.create, self.runners = create, runners

    def inference_runners(self, config: object) -> tuple[type[InferenceRunner], ...]:
        return self.runners(config)

    def get_plugin(self, *args: object, **kwargs: object) -> object:
        return self.create()


def stand_in(module: AvatarModule, name: str, create, runners=lambda config: ()) -> ResolvedPlugin:
    """A plugin the configuration names, resolved in place of any installed one."""
    return ResolvedPlugin(module, name, _Factory(create, runners), None)


# What the session tests' configurations name and no installed package provides.
NAMED = (
    (AvatarModule.PROVIDER_LLM, "scripted"),
    (AvatarModule.MEMORY, "doctor"),
    (AvatarModule.PERSONA, "doctor"),
)


def resolvable(monkeypatch: object, *names: tuple[AvatarModule, str]) -> None:
    """Test-only plugins resolve in this process, as their stand-ins do in the diagnostic one;
    nothing here creates them."""
    for module, name in names or NAMED:
        monkeypatch.setitem(resolution._resolved, (module, name), stand_in(module, name, object))


def _factories(namespace: str) -> list[type[AvatarModulePlugin]]:
    """The factory classes a built-in plugin package declares."""
    from importlib.metadata import entry_points

    return [
        entry.load()
        for module in AvatarModule
        for entry in entry_points(group=module.group)
        if entry.module.split(".")[:3] == ["alphaavatar", "plugins", namespace]
    ]


def child(*args: object) -> None:
    """The diagnostic process's entry under test: guarded, stood in for, then the real one."""
    spec = json.loads(os.environ[SPEC])
    files = Path(spec["files"])
    (files / "pid").write_text(str(os.getpid()))
    with open(files / "runs.jsonl", "a") as runs:  # Each run's plan, rounds and start bound
        tasks = [task.name for task in args[8].tasks] if args[8] is not None else None
        line = {"rounds": args[7], "runners": args[6].runners, "tasks": tasks}
        runs.write(json.dumps(line) + "\n")
    _deny_network(files / "network", spec.get("loopback"))
    install(spec, files)
    from alphaavatar.host.doctor import process

    process._main(*args)


def install(spec: dict, files: Path) -> None:
    """The stand-ins, resolved where the configuration names its plugins and runners."""
    from alphaavatar.host.doctor import samples, session

    llm = ScriptedLLM(files, **spec.get("llm", {}))
    stt = ScriptedSTT(list(spec.get("stt", ())), files, chatty=spec.get("stdout", False))
    tts = ScriptedTTS(**spec.get("tts", {}))
    vision = tuple(map(_runner, spec.get("vision_runners", ())))
    for module, name, create, runners in (
        (AvatarModule.PROVIDER_LLM, "scripted", lambda: llm, None),
        (AvatarModule.VOICE_STT, "openai_segment", lambda: stt, None),
        (AvatarModule.VOICE_TTS, "openai", lambda: tts, None),
        (AvatarModule.MEMORY, "doctor", NullMemory, None),
        # Planned only while vision is on, as a camera consumer's runner is.
        (AvatarModule.PERSONA, "doctor", NullPersona, lambda c: vision if c.vision.enabled else ()),
    ):
        resolution._resolved[(module, name)] = stand_in(
            module, name, create, runners or (lambda config: ())
        )
    # The named built-in plugins' implementations use these runners instead of their own.
    for name, runners in spec.get("runners", {}).items():
        found = tuple(map(_runner, runners))
        for factory in _factories(name):
            factory.inference_runners = lambda self, config, f=found: f
    # A second of loud noise is speech to the stand-in VAD, in two stretches, as two sentences
    # 0.2 s apart, too short a pause to close a segment; silence follows, as from a mic.
    noise = np.random.default_rng(7).standard_normal(samples.SAMPLE_RATE) * 6000
    noise[round(0.45 * samples.SAMPLE_RATE) : round(0.65 * samples.SAMPLE_RATE)] = 0
    voiced = noise.astype("<i2").tobytes()
    samples.speech = lambda name: samples.Speech(name, voiced, 1.0)
    if spec.get("drop_speech"):
        # Context builds the Turn without its speech, or the committed text standing in for
        # it: its input and frames stay.
        from alphaavatar.plugins.context.builder import ContextBuilder
        from alphaavatar.plugins.context.builder.renderer.input import xml

        xml._speech_parts = lambda *args, **kwargs: ()
        build = ContextBuilder.build
        ContextBuilder.build = lambda self, *, snapshot, **kwargs: build(
            self, snapshot=dataclasses.replace(snapshot, text=None), **kwargs
        )
    if spec.get("slow_assembly"):
        # The Context build has returned; the loop then awaits this long before the request
        # goes on: that wait is the request's assembly, not the build.
        from alphaavatar.agents.avatar.loop.enums import LoopState
        from alphaavatar.plugins.loop.feedback import LoopFeedback

        change = LoopFeedback.change

        async def assembling(self: object, state: LoopState, **kwargs: object) -> None:
            if state in (LoopState.MODEL, LoopState.FINALIZING):
                await asyncio.sleep(spec["slow_assembly"])
            await change(self, state, **kwargs)

        LoopFeedback.change = assembling
    if spec.get("slow_scan"):
        # A model cache that takes this long to scan: the start's own time must not hold it.
        import time

        scan = session._cached_bytes

        def slow(root: object) -> int:
            time.sleep(spec["slow_scan"])
            return scan(root)

        session._cached_bytes = slow
    if spec.get("crash"):
        # A process that dies of an uncaught error, as a broken install would.
        async def crash(*args: object, **kwargs: object):
            raise RuntimeError("stand-in session crashed")

        session.diagnose_session = crash
    if spec.get("deaf"):
        # A process that neither hears the stop nor keeps to its budget: only its group's
        # end reclaims it.
        diagnose = session.diagnose_session

        async def deaf(*args: object, limits: object, stop: object, **kwargs: object):
            print("stand-in session ignoring its stop", file=sys.stderr, flush=True)
            endless = session.Budget(3600.0, 3600.0, 3600.0, 3600.0)
            return await diagnose(*args, limits=endless, stop=asyncio.Event(), **kwargs)

        session.diagnose_session = deaf


def _runner(name: str) -> type[InferenceRunner]:
    """A runner by its name here or among the samples, or by ``module:name`` anywhere."""
    import inference_runner_samples

    if ":" in name:
        module, _, attribute = name.partition(":")
        return getattr(importlib.import_module(module), attribute)
    return getattr(sys.modules[__name__], name, None) or getattr(inference_runner_samples, name)


def _deny_network(log: Path, port: int | None = None) -> None:
    """The test process's guard, in the diagnostic process: local AF_UNIX paths only, and
    the one loopback ``port`` the test serves itself, if any."""
    connect, resolve = socket.socket.connect, socket.getaddrinfo
    owned = ("127.0.0.1", port)

    def refuse(operation: str):
        def call(*args: object, **kwargs: object) -> object:
            with log.open("a") as stream:
                stream.write(f"{operation}\n")  # Logged even when the caller swallows it.
            raise PermissionError(f"Deterministic tests may not use the network: {operation}")

        return call

    def local(sock: socket.socket, address: object) -> None:
        if sock.family == socket.AF_UNIX and type(address) is str and os.path.isabs(address):
            return connect(sock, address)
        if port is not None and sock.family == socket.AF_INET and address == owned:
            return connect(sock, address)
        return refuse("socket.connect")(sock, address)

    def lookup(host: object, service: object, *args: object, **kwargs: object) -> object:
        if port is not None and (host, service) in (owned, ("127.0.0.1", str(port))):
            return resolve(host, service, *args, **kwargs)
        return refuse("socket.getaddrinfo")(host, service, *args, **kwargs)

    socket.socket.connect = local
    socket.getaddrinfo = lookup
    for name in ("connect_ex", "sendto"):
        setattr(socket.socket, name, refuse(f"socket.{name}"))
    for name in ("gethostbyname", "gethostbyname_ex", "create_connection"):
        setattr(socket, name, refuse(f"socket.{name}"))
