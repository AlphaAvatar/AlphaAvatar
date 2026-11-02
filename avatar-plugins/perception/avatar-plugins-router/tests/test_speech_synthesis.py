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
"""Speech synthesis, alignment and caption settlement over a real OutputRuntime; offline TTS."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pytest

from alphaavatar.agents.avatar.voice import TTSBase, TTSStreamBase
from alphaavatar.agents.configs.runtime_config import RuntimeConfig
from alphaavatar.agents.runtime import AvatarRuntime, StateRuntime
from alphaavatar.agents.runtime.inference import InferenceExecutor
from alphaavatar.core.env import EnvOutput
from alphaavatar.core.media import AudioFrame
from alphaavatar.core.output import OutputRuntime
from alphaavatar.core.output.enums import (
    OutputControlType,
    OutputKind,
    OutputLane,
    OutputPlaybackType,
    OutputTextMode,
)
from alphaavatar.core.output.schemas import (
    OutputPlayback,
    OutputScope,
    OutputSource,
    OutputTextAudioAlignment,
    OutputTextChunk,
)
from alphaavatar.core.session import SessionRuntime
from alphaavatar.core.workspace import WorkspacePaths
from alphaavatar.plugins.router.processors.speech import (
    SpeechSynthesisProcessor,
    TranscriptSynchronizationProcessor,
)

HANG_GUARD = 10
RATE, SAMPLES = 16_000, 160


def avatar_runtime(root: Path) -> AvatarRuntime:
    workspace, session = WorkspacePaths.from_root(root), SessionRuntime(session_id="session")
    return AvatarRuntime.create(
        workspace=workspace,
        session=session,
        session_path=workspace.data.sessions.get(session.session_id, date(2026, 1, 1)),
        state=StateRuntime(),
        config=RuntimeConfig(),
        inference=InferenceExecutor("/unused/inference.sock"),
    )


async def wait_until(condition: Callable[[], bool], failure: str) -> None:
    try:
        async with asyncio.timeout(HANG_GUARD):
            while not condition():
                await asyncio.sleep(0.001)
    except TimeoutError:
        pytest.fail(failure, pytrace=False)


def marker(request: int, frame: int) -> bytes:
    return request.to_bytes(4, "little") + frame.to_bytes(2, "little")


def request_of(marker: bytes) -> int:
    return int.from_bytes(marker[:4], "little")


class OfflineStream(TTSStreamBase):
    def __init__(self, tts: OfflineTTS, text: str, index: int) -> None:
        self.text, self.index, self._tts, self.closed = text, index, tts, False
        # Each frame encodes (request, frame) so playout order is checkable byte for byte.
        self._frames = [
            AudioFrame(RATE, 1, SAMPLES, (marker(index, frame) * SAMPLES)[: 2 * SAMPLES])
            for frame in range(max(1, len(text) // 8))
        ]
        self.request_id = f"request-{index}"

    async def __anext__(self) -> AudioFrame:
        if self.closed or not self._frames:
            raise StopAsyncIteration
        if self._tts.self_cancel == self.index:
            raise asyncio.CancelledError  # A provider bug, not a caller's cancellation.
        while self._tts.budget is not None and len(self._tts.emitted) >= self._tts.budget:
            self._tts.more.clear()
            self._tts.stalled += 1
            try:
                await self._tts.more.wait()
            finally:
                self._tts.stalled -= 1
        frame = self._frames.pop(0)
        self._tts.emitted.append(frame.data[:6])
        return frame

    async def aclose(self) -> None:
        self.closed = True


class OfflineTTS(TTSBase):
    def __init__(self) -> None:
        self.streams: list[OfflineStream] = []
        self.emitted: list[bytes] = []
        self.budget: int | None = None  # Frames the provider may emit before it stalls.
        self.more = asyncio.Event()
        self.stalled = 0
        self.self_cancel: int | None = None  # Request whose stream cancels itself.

    def allow(self, budget: int | None) -> None:
        self.budget = budget
        self.more.set()

    @property
    def sample_rate(self) -> int:
        return RATE

    @property
    def num_channels(self) -> int:
        return 1

    def synthesize(self, text: str) -> OfflineStream:
        stream = OfflineStream(self, text, len(self.streams))
        self.streams.append(stream)
        return stream

    async def aclose(self) -> None:
        pass


@dataclass
class Player:
    """A local transport: plays PCM in order and reports queue receipts, never captions."""

    output: OutputRuntime
    pcm: dict[str, list[bytes]] = field(default_factory=dict)
    receipts: list[tuple[str, OutputPlaybackType]] = field(default_factory=list)
    task: asyncio.Task | None = None

    async def start(self) -> None:
        subscription = await self.output.stream.subscribe(
            "player", kinds=(OutputKind.AUDIO_FRAME, OutputKind.CONTROL), max_pending=64
        )
        self.task = asyncio.create_task(self._run(subscription), name="test_player")

    async def _receipt(self, identity, kind: OutputPlaybackType) -> None:
        played = len(self.pcm.get(identity.output_id, ())) * SAMPLES / RATE
        await self.output.publish(
            EnvOutput(
                kind=OutputKind.PLAYBACK,
                lane=identity.lane,
                scope=identity.scope,
                source=OutputSource("test.player"),
                output_id=identity.output_id,
                payload=OutputPlayback(kind, played, played, 0.0),
                metadata={"measurement": "local_audio_queue"},
            )
        )
        self.receipts.append((identity.output_id, kind))

    async def _run(self, subscription) -> None:
        while True:
            event = (await subscription.get()).output
            control = event.payload
            if event.kind == OutputKind.AUDIO_FRAME:
                if self.output.can_deliver(event.output_id):
                    first = event.output_id not in self.pcm
                    self.pcm.setdefault(event.output_id, []).append(control.data[:6])
                    kind = OutputPlaybackType.STARTED if first else OutputPlaybackType.PROGRESS
                    await self._receipt(self.output.output_identity(event.output_id), kind)
            elif control.type == OutputControlType.INTERRUPT:
                for identity in control.targets:
                    await self._receipt(identity, OutputPlaybackType.INTERRUPTED)
            elif control.type == OutputControlType.COMPLETE:
                identity = self.output.output_identity(event.output_id)
                await self._receipt(identity, OutputPlaybackType.FINISHED)

    async def stop(self) -> None:
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)


@dataclass
class Speech:
    runtime: AvatarRuntime
    tts: OfflineTTS
    synthesis: SpeechSynthesisProcessor
    captions: TranscriptSynchronizationProcessor
    player: Player
    consumers: list[asyncio.Task] = field(default_factory=list)

    @property
    def output(self) -> OutputRuntime:
        return self.runtime.output

    async def record(self, name: str, kinds: tuple[OutputKind, ...], **options) -> list[EnvOutput]:
        subscription = await self.output.stream.subscribe(name, kinds=kinds, **options)
        return self.consume(subscription)

    def consume(self, subscription, *, lag: int = 0) -> list[EnvOutput]:
        events: list[EnvOutput] = []

        async def collect() -> None:
            while True:
                events.append((await subscription.get()).output)
                for _ in range(lag):
                    await asyncio.sleep(0)  # A slow presentation consumer.

        self.consumers.append(asyncio.create_task(collect(), name=f"test_{subscription.name}"))
        return events

    async def say(self, output_id: str, *chunks: str, run: str = "run") -> None:
        scope = OutputScope(context_id="context", turn_id="turn", run_id=run)
        for value in chunks:
            await self.output.publish(
                EnvOutput(
                    kind=OutputKind.TEXT_CHUNK,
                    lane=OutputLane.ASSISTANT,
                    scope=scope,
                    source=OutputSource("test.agent"),
                    output_id=output_id,
                    payload=OutputTextChunk(
                        text=value, mode=OutputTextMode.AUDIO_SYNCED, replace_lane=False
                    ),
                )
            )
        await self.output.finish_text(output_id=output_id, turn_id="turn", run_id=run)


@pytest.fixture
async def speech(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Speech]:
    runtime, tts = avatar_runtime(tmp_path / "workspace"), OfflineTTS()
    runtime.output.activate_run("run")
    options = {"flush_interval": 0.01, **getattr(request, "param", {})}
    synthesis = SpeechSynthesisProcessor(runtime=runtime, tts=tts, **options)
    captions = TranscriptSynchronizationProcessor(runtime=runtime)
    player = Player(runtime.output)
    for component in (player, captions, synthesis):
        await component.start()
    speech = Speech(runtime, tts, synthesis, captions, player)
    yield speech
    for task in speech.consumers:
        task.cancel()
    await asyncio.gather(*speech.consumers, return_exceptions=True)
    for component in (synthesis, captions, player):
        await component.stop()
    await runtime.aclose()


def final_alignments(events: list[EnvOutput], output_id: str) -> list[OutputTextAudioAlignment]:
    finals = {}
    for event in events:
        if event.kind == OutputKind.ALIGNMENT and event.output_id == output_id:
            if event.payload.duration_final:
                finals[event.payload.alignment_id] = event.payload
    return list(finals.values())


async def test_back_to_back_short_sentences_keep_pcm_and_final_alignment_exact(
    speech: Speech,
) -> None:
    alignments = await speech.record("alignments", (OutputKind.ALIGNMENT,))
    text = "".join(f"Sentence number {index} is short. " for index in range(12))
    await speech.say("answer", *(text[i : i + 7] for i in range(0, len(text), 7)))

    await wait_until(lambda: speech.output.transcript_finalized("answer"), "no final transcript")
    finals = final_alignments(alignments, "answer")
    played = speech.player.pcm["answer"]
    # PCM reaches the player in exactly the synthesized order, with nothing replayed or lost.
    assert played == speech.tts.emitted
    assert [stream.text for stream in speech.tts.streams] == [item.text for item in finals]
    assert "".join(item.text for item in finals) == text
    assert all(stream.closed for stream in speech.tts.streams)
    # Final measured timing is contiguous and equals each phrase's admitted PCM duration.
    offset = 0.0
    for item, stream in zip(finals, speech.tts.streams, strict=True):
        frames = max(1, len(stream.text) // 8)
        assert item.start_time_sec == pytest.approx(offset)
        assert item.end_time_sec - item.start_time_sec == pytest.approx(frames * SAMPLES / RATE)
        assert not item.partial and item.timing_source == "measured_audio"
        offset = item.end_time_sec
    assert (speech.output.terminal_reason("answer"), speech.player.receipts[-1]) == (
        "output_completed",
        ("answer", OutputPlaybackType.FINISHED),
    )


def suspended_in(task: asyncio.Task) -> list[str]:
    """Names of the coroutines a suspended task is awaiting, outermost first."""
    names, awaited = [], task.get_coro()
    while awaited is not None and hasattr(awaited, "cr_code"):
        names.append(awaited.cr_code.co_name)
        awaited = awaited.cr_await
    return names


SHORT_PHRASES = {"segment_chars": 32, "min_segment_chars": 8}


@pytest.mark.parametrize("speech", [SHORT_PHRASES], indirect=True)
async def test_alignment_capacity_pressure_pauses_phrase_admission_not_pcm(speech: Speech) -> None:
    probe = await speech.output.stream.subscribe(
        "alignment_probe", kinds=(OutputKind.ALIGNMENT,), max_pending=1
    )
    text = "".join(f"Phrase {index} waits. " for index in range(30))
    await speech.say("answer", text)

    def admission_blocked() -> bool:
        job = speech.synthesis._jobs.get("answer")
        return job is not None and "reserve_alignment" in suspended_in(job.task)

    await wait_until(admission_blocked, "alignment pressure never reached phrase admission")
    *admitted, blocked = speech.tts.streams
    # Eight reserved phrases played in full; the blocked one holds only its first frame.
    assert len(admitted) == 8 and all(stream.closed for stream in admitted) and not blocked.closed
    assert speech.player.pcm["answer"] == speech.tts.emitted[:-1]

    events = speech.consume(probe)
    await wait_until(lambda: speech.output.transcript_finalized("answer"), "speech never settled")
    finals = final_alignments(events, "answer")
    assert "".join(item.text for item in finals) == text
    assert [item.start_time_sec for item in finals[1:]] == [
        item.end_time_sec for item in finals[:-1]
    ]
    assert speech.player.pcm["answer"] == speech.tts.emitted


async def test_slow_caption_consumer_never_paces_pcm(speech: Speech) -> None:
    subtitles = await speech.output.stream.subscribe(
        "subtitles", kinds=(OutputKind.TRANSCRIPT_CHUNK,), fail_on_overflow=True, max_pending=256
    )
    text = "Captions may lag behind audio. They catch up afterwards."
    await speech.say("answer", text)

    await wait_until(
        lambda: ("answer", OutputPlaybackType.FINISHED) in speech.player.receipts,
        "playout waited for captions",
    )
    assert speech.player.pcm["answer"] == speech.tts.emitted
    chunks = []
    async with asyncio.timeout(HANG_GUARD):
        while not chunks or not chunks[-1].is_final:
            chunks.append((await subtitles.get()).output.payload)
    # Captions were produced during playout and waited in the consumer's own queue.
    assert len(chunks) > 2 and "".join(chunk.text for chunk in chunks) == text
    assert chunks[0].is_first and not chunks[-1].interrupted


async def stall(speech: Speech, frames: int) -> list[bytes]:
    """Let the provider emit exactly `frames`, then wait until playout drained and TTS stalled."""
    await wait_until(
        lambda: speech.tts.stalled and speech.player.pcm.get("answer") == speech.tts.emitted,
        "speech never stalled at its frame budget",
    )
    assert len(speech.tts.emitted) == frames
    return list(speech.tts.emitted)


def audio_completion(events: list[EnvOutput], output_id: str):
    return next(
        event.payload
        for event in events
        if event.kind == OutputKind.CONTROL
        and event.output_id == output_id
        and event.payload.type == OutputControlType.AUDIO_COMPLETE
    )


@pytest.mark.parametrize("cut", [3, 8], ids=["mid_phrase", "awaiting_next_phrase"])
@pytest.mark.parametrize("trigger", ["barge_in", "stale_run"])
async def test_interrupted_speech_withholds_old_pcm_and_text_but_settles_closing_facts(
    speech: Speech, trigger: str, cut: int
) -> None:
    output, tts = speech.output, speech.tts
    events = await speech.record(
        "observer", (OutputKind.ALIGNMENT, OutputKind.TRANSCRIPT_CHUNK, OutputKind.CONTROL)
    )
    text = "".join(f"Old answer sentence {index} keeps going. " for index in range(8))
    tts.allow(cut)  # The first phrase has eight frames: stall inside it, or before the next.
    await speech.say("answer", text)
    played = await stall(speech, cut)
    assert len(tts.streams) == (1 if cut == 3 else 2)

    if trigger == "barge_in":
        await output.interrupt(output_id="answer", reason="barge_in")
    output.activate_run("next")  # Without barge-in, the new run's first text retires the job.
    await speech.say("fresh", "A new reply.", run="next")
    tts.allow(None)

    # Reclamation is proven before any processor or runtime close can mask it.
    await wait_until(lambda: output.transcript_finalized("answer"), "old speech never settled")
    await wait_until(lambda: output.transcript_finalized("fresh"), "new speech never settled")
    assert not [task for task in asyncio.all_tasks() if task.get_name() == "tts:answer"]
    assert all(stream.closed for stream in tts.streams)
    assert speech.player.pcm["answer"] == played
    (fresh,) = [stream.index for stream in tts.streams if stream.text == "A new reply."]
    assert speech.player.pcm["fresh"] == [item for item in tts.emitted if request_of(item) == fresh]
    assert ("answer", OutputPlaybackType.INTERRUPTED) in speech.player.receipts
    assert ("answer", OutputPlaybackType.FINISHED) not in speech.player.receipts
    late = OutputTextChunk(text="late", mode=OutputTextMode.AUDIO_SYNCED, replace_lane=False)
    scope = OutputScope(context_id="context", turn_id="turn", run_id="run")
    stale = EnvOutput(
        kind=OutputKind.TEXT_CHUNK,
        lane=OutputLane.ASSISTANT,
        scope=scope,
        source=OutputSource("test.agent"),
        output_id="answer",
        payload=late,
    )
    assert await output.publish(stale) is None

    reason = "barge_in" if trigger == "barge_in" else "synthesis_interrupted"
    assert audio_completion(events, "answer").reason == reason
    captions = [
        event.payload
        for event in events
        if event.kind == OutputKind.TRANSCRIPT_CHUNK and event.output_id == "answer"
    ]
    assert captions[-1].is_final and captions[-1].interrupted
    assert text.startswith("".join(caption.text for caption in captions))
    # A phrase cut mid-PCM keeps a sealed, explicitly partial timing fact.
    assert [item.partial for item in final_alignments(events, "answer")] == [cut == 3]


async def test_interrupted_alignment_covers_audio_already_delivered_to_a_consumer(
    speech: Speech,
) -> None:
    output, player = speech.output, speech.player
    alignments = await speech.record("alignments", (OutputKind.ALIGNMENT,))
    # A second reliable audio consumer stops reading, so the next frame reaches the player
    # while its publication still waits on this queue.
    await output.stream.subscribe("lagging_audio", kinds=(OutputKind.AUDIO_FRAME,), max_pending=1)
    await speech.say("answer", "One long phrase keeps speaking for many frames here.")
    await wait_until(lambda: len(player.pcm.get("answer", ())) == 2, "two frames never played")

    await output.interrupt(turn_id="turn", reason="barge_in")
    await wait_until(lambda: output.transcript_finalized("answer"), "old speech never settled")
    delivered = len(player.pcm["answer"]) * SAMPLES / RATE
    (final,) = final_alignments(alignments, "answer")
    # The interrupted publication returned nothing, yet the player already holds its frame.
    assert delivered == pytest.approx(2 * SAMPLES / RATE)
    assert final.partial and final.start_time_sec == 0.0
    assert final.end_time_sec == pytest.approx(delivered)


async def test_revoked_answer_awaiting_tts_first_audio_is_interrupted_not_failed(
    speech: Speech, caplog: pytest.LogCaptureFixture
) -> None:
    output, tts = speech.output, speech.tts
    events = await speech.record("observer", (OutputKind.CONTROL,))
    tts.allow(8)
    await speech.say("answer", "".join(f"Old answer sentence {i} keeps going. " for i in range(8)))
    await stall(speech, 8)  # The next phrase's TTS request awaits its first audio.

    # Engine barge-in order: revoke the run, then publish the interrupt. TTS first audio
    # arriving in between is an ordinary race with a real provider.
    output.revoke_run("run")
    tts.allow(None)
    await output.interrupt(turn_id="turn", reason="barge_in")
    await wait_until(lambda: output.transcript_finalized("answer"), "old speech never settled")

    interrupts = [
        event.payload.reason
        for event in events
        if event.output_id is None and event.payload.type == OutputControlType.INTERRUPT
    ]
    # A revoked output is an interruption on every path, never a synthesis failure.
    assert audio_completion(events, "answer").reason != "speech_synthesis_failed"
    assert interrupts == ["barge_in"]
    assert not [record for record in caplog.records if record.levelname == "ERROR"]


async def test_provider_self_cancellation_on_an_active_output_remains_a_failure(
    speech: Speech, caplog: pytest.LogCaptureFixture
) -> None:
    output, tts = speech.output, speech.tts
    events = await speech.record("observer", (OutputKind.CONTROL,))
    tts.self_cancel = 0
    await speech.say("answer", "A provider that cancels itself is not an interruption.")
    await wait_until(lambda: output.transcript_finalized("answer"), "speech never settled")

    # Only a revoked output may turn a preparation cancellation into an interruption.
    assert audio_completion(events, "answer").reason == "speech_synthesis_failed"
    (failure,) = [record for record in caplog.records if record.levelname == "ERROR"]
    assert str(failure.exc_info[1]) == "TTS preparation cancelled itself"
    assert speech.player.pcm.get("answer") is None


@pytest.mark.stress
@pytest.mark.parametrize("speech", [SHORT_PHRASES], indirect=True)
async def test_back_to_back_answers_keep_pcm_and_alignment_under_slow_presentation(
    speech: Speech, stress_seconds: float
) -> None:
    output, tts = speech.output, speech.tts
    probe = await output.stream.subscribe(
        "alignment_probe", kinds=(OutputKind.ALIGNMENT,), max_pending=2
    )
    subtitles = await output.stream.subscribe(
        "subtitles", kinds=(OutputKind.TRANSCRIPT_CHUNK,), fail_on_overflow=True, max_pending=256
    )
    alignments = speech.consume(probe, lag=5)  # Presentation lags the PCM path.
    captions = speech.consume(subtitles, lag=5)
    deadline, rounds, frames = time.monotonic() + stress_seconds, 0, 0
    started = time.monotonic()
    while rounds < 3 or time.monotonic() < deadline:
        run, output_id = f"run-{rounds}", f"answer-{rounds}"
        output.activate_run(run)
        first = len(tts.streams)
        text = "".join(f"Reply {rounds} line {index}. " for index in range(3 + rounds % 9))
        await speech.say(output_id, *(text[i : i + 5] for i in range(0, len(text), 5)), run=run)
        await wait_until(
            lambda key=output_id: output.transcript_finalized(key), "answer never settled"
        )
        streams = tts.streams[first:]
        expected = [item for item in tts.emitted if request_of(item) >= first]
        assert speech.player.pcm.pop(output_id) == expected
        finals = final_alignments(alignments, output_id)
        assert [item.text for item in finals] == [stream.text for stream in streams]
        ends = [item.end_time_sec for item in finals[:-1]]
        assert [item.start_time_sec for item in finals[1:]] == pytest.approx(ends)
        await wait_until(
            lambda key=output_id: any(c.output_id == key and c.payload.is_final for c in captions),
            "captions never caught up",
        )
        spoken = "".join(c.payload.text for c in captions if c.output_id == output_id)
        assert spoken == text
        frames += len(expected)
        rounds += 1
    elapsed = time.monotonic() - started
    print(
        f"synthetic speech stress: answers={rounds} phrases={len(tts.streams)} "
        f"frames={frames} answers_per_second={rounds / elapsed:.1f}"
    )
