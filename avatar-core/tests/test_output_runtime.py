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
"""OutputRuntime delivery, interruption and terminal-publication ownership; no real transport."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

import pytest

from alphaavatar.core.env.output import EnvOutput
from alphaavatar.core.media import AudioFrame
from alphaavatar.core.output import OutputRuntime, OutputSubscription
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
    OutputTranscriptChunk,
)

HANG_GUARD = 10
SOURCE = OutputSource("test")
RATE = 16_000


def scope(run: str = "run") -> OutputScope:
    return OutputScope(context_id="context", turn_id="turn", run_id=run)


def content(output_id: str, kind: OutputKind, payload: object, *, run: str = "run") -> EnvOutput:
    return EnvOutput(
        kind=kind,
        lane=OutputLane.ASSISTANT,
        scope=scope(run),
        source=SOURCE,
        payload=payload,
        output_id=output_id,
    )


def text(
    output_id: str, value: str, *, run: str = "run", mode: OutputTextMode = OutputTextMode.MIRROR
) -> EnvOutput:
    chunk = OutputTextChunk(text=value, mode=mode, replace_lane=False)
    return content(output_id, OutputKind.TEXT_CHUNK, chunk, run=run)


def pcm(output_id: str, marker: int, *, run: str = "run") -> EnvOutput:
    frame = AudioFrame(RATE, 1, 160, bytes([marker % 256]) * 320)
    return content(output_id, OutputKind.AUDIO_FRAME, frame, run=run)


def aligned(output_id: str, index: int, *, run: str = "run") -> EnvOutput:
    alignment = OutputTextAudioAlignment(
        text=f"phrase {index}",
        alignment_id=f"{output_id}:{index}",
        source_chunk_ids=("chunk",),
        start_time_sec=0.01 * index,
        end_time_sec=0.01 * (index + 1),
    )
    return content(output_id, OutputKind.ALIGNMENT, alignment, run=run)


def playback(
    output_id: str, kind: OutputPlaybackType, seconds: float, *, run: str = "run"
) -> EnvOutput:
    receipt = OutputPlayback(kind, seconds, seconds, 0.0)
    return content(output_id, OutputKind.PLAYBACK, receipt, run=run)


async def wait_until(condition: Callable[[], bool], failure: str) -> None:
    try:
        async with asyncio.timeout(HANG_GUARD):
            while not condition():
                await asyncio.sleep(0)
    except TimeoutError:
        pytest.fail(failure, pytrace=False)


def pending_pushes(before: set[asyncio.Task]) -> set[asyncio.Task]:
    return {
        task
        for task in asyncio.all_tasks() - before
        if task.get_coro().__qualname__ == "OutputSubscription.push" and not task.done()
    }


async def drain(subscription: OutputSubscription) -> list[EnvOutput]:
    received = []
    while subscription._control_events or subscription._data_events:
        received.append((await subscription.get()).output)
    return received


def runtime(**options: object) -> OutputRuntime:
    output = OutputRuntime(session_id="session", **options)
    output.activate_run("run")
    return output


async def test_interrupt_withholds_admitted_media_and_still_settles_closing_facts() -> None:
    output = runtime()
    player = await output.stream.subscribe("player", max_pending=2)
    await output.publish(text("speech", "hello", mode=OutputTextMode.AUDIO_SYNCED))
    await output.publish(pcm("speech", 1))
    before = asyncio.all_tasks()
    blocked = asyncio.create_task(output.publish(pcm("speech", 2)))
    await wait_until(lambda: len(pending_pushes(before)) == 1, "the frame never met backpressure")

    async with asyncio.timeout(HANG_GUARD):
        interrupted = await output.interrupt(output_id="speech", reason="barge_in")
        assert await blocked is None
    assert interrupted is not None and not output.can_deliver("speech")
    # The withheld frame was sequenced before the interrupt; the audio barrier still covers it.
    completed = await output.finish_audio(
        output_id="speech", lane=OutputLane.ASSISTANT, turn_id="turn", reason="barge_in"
    )
    assert completed.output.payload.barrier.last_audio_sequence == interrupted.sequence - 1

    received = await drain(player)
    assert [(item.kind, getattr(item.payload, "type", None)) for item in received] == [
        (OutputKind.CONTROL, OutputControlType.INTERRUPT),
        (OutputKind.CONTROL, OutputControlType.AUDIO_COMPLETE),
    ]
    # The playback receipt and an un-flagged final transcript are still admitted as facts.
    receipt = await output.publish(playback("speech", OutputPlaybackType.INTERRUPTED, 0.01))
    final = await output.publish(
        content("speech", OutputKind.TRANSCRIPT_CHUNK, OutputTranscriptChunk("", is_final=True))
    )
    assert receipt is not None and final.output.payload.interrupted
    assert output.terminal_reason("speech") == "barge_in" and output.transcript_finalized("speech")
    assert asyncio.all_tasks() - before == set()
    await output.aclose()


async def test_audio_barrier_waits_for_media_held_by_reliable_backpressure() -> None:
    output = runtime()
    captions = await output.stream.subscribe("captions", max_pending=1)
    await output.publish(text("speech", "hello", mode=OutputTextMode.AUDIO_SYNCED))
    before = asyncio.all_tasks()
    media = [
        asyncio.create_task(output.publish(item))
        for index in range(3)
        for item in (pcm("speech", index), aligned("speech", index))
    ]
    await wait_until(lambda: len(pending_pushes(before)) == 6, "media never met backpressure")
    finishing = asyncio.create_task(
        output.finish_audio(output_id="speech", lane=OutputLane.ASSISTANT, turn_id="turn")
    )
    received: list[EnvOutput] = []
    async with asyncio.timeout(HANG_GUARD):
        while not received or received[-1].kind != OutputKind.CONTROL:
            received.append((await captions.get()).output)
        published = [(await task).sequence for task in media]
        completed = await finishing
    # Every admitted frame and alignment precedes the completion fact that seals them.
    assert [item.kind for item in received] == [
        OutputKind.TEXT_CHUNK,
        *(OutputKind.AUDIO_FRAME, OutputKind.ALIGNMENT) * 3,
        OutputKind.CONTROL,
    ]
    frames = [item.payload.data[0] for item in received if item.kind == OutputKind.AUDIO_FRAME]
    assert frames == [0, 1, 2]
    barrier = completed.output.payload.barrier
    assert (barrier.last_audio_sequence, barrier.last_alignment_sequence) == tuple(published[-2:])
    # Media admitted after the seal is refused instead of trailing its completion fact.
    assert await output.publish(pcm("speech", 3)) is None
    await output.aclose()


async def test_stale_run_content_is_withheld_even_after_admission() -> None:
    output = runtime()
    reader = await output.stream.subscribe("reader")
    assert await output.publish(text("old", "stale")) is not None
    output.activate_run("next")

    assert not output.is_active("old")
    assert await output.publish(text("old", "late")) is None
    assert await output.publish(text("new", "fresh", run="next")) is not None
    # The queued chunk of the revoked run is filtered at delivery, not only at admission.
    async with asyncio.timeout(HANG_GUARD):
        assert (await reader.get()).output.payload.text == "fresh"
    assert not reader._data_events
    await output.aclose()


async def test_terminal_publication_timeout_retires_delivery_instead_of_hanging() -> None:
    output = runtime(terminal_timeout_sec=0.05)
    await output.stream.subscribe("stalled", max_pending=1)
    await output.publish(text("answer", "done"))

    started = time.monotonic()
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(HANG_GUARD):
            await output.complete(lane=OutputLane.ASSISTANT, output_id="answer", turn_id="turn")
    # The runtime's own terminal deadline fired, not this test's hang guard.
    assert time.monotonic() - started < HANG_GUARD / 2
    assert not output.accepts_run("run")
    with pytest.raises(RuntimeError, match="delivery is unavailable"):
        await output.publish(text("answer", "after"))
    with pytest.raises(ExceptionGroup) as closed:
        await output.aclose()
    (failure,) = closed.value.exceptions
    assert "publication aborted" in str(failure)


async def test_cancelled_terminal_caller_reaps_its_publication_before_close() -> None:
    output = runtime()
    await output.stream.subscribe("stalled", max_pending=1)
    await output.publish(text("answer", "done"))
    before = asyncio.all_tasks()
    caller = asyncio.create_task(
        output.complete(lane=OutputLane.ASSISTANT, output_id="answer", turn_id="turn")
    )
    await wait_until(lambda: pending_pushes(before), "completion never met backpressure")

    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    # Checked before aclose(): the owned publication and its fan-out are already reclaimed.
    assert asyncio.all_tasks() - before == set()
    # A half-delivered terminal fact cannot be retried, so realtime delivery fails closed.
    assert not output.accepts_run("run")
    with pytest.raises(ExceptionGroup, match="Output publication shutdown failed"):
        await output.aclose()


async def test_cancelled_terminal_of_a_revoked_run_is_superseded_not_fatal() -> None:
    output = runtime()
    stalled = await output.stream.subscribe("stalled", max_pending=1)
    await output.publish(text("answer", "done"))
    before = asyncio.all_tasks()
    caller = asyncio.create_task(
        output.complete(lane=OutputLane.ASSISTANT, output_id="answer", turn_id="turn")
    )
    await wait_until(lambda: pending_pushes(before), "completion never met backpressure")

    output.revoke_run("run")
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert asyncio.all_tasks() - before == set()
    # The stale run's queued text still occupies the stalled consumer; delivery itself survives.
    await output.stream.unsubscribe(stalled.name)
    output.activate_run("next")
    assert output.accepts_run("next")
    assert await output.publish(text("fresh", "new", run="next")) is not None
    await output.aclose()


async def test_unreliable_interrupt_overflow_retires_only_that_observer() -> None:
    output = runtime()
    observer = await output.stream.subscribe("observer", max_pending=1, reliable=False)
    player = await output.stream.subscribe("player", max_pending=8)
    for output_id in ("first", "second"):
        await output.publish(text(output_id, output_id))
        await output.interrupt(output_id=output_id, reason="barge_in")

    with pytest.raises(RuntimeError, match="'observer' failed") as failed:
        await observer.get()
    assert "interrupt queue overflowed" in str(failed.value.__cause__)
    assert output.accepts_run("run")
    # Interrupts also withdrew each target's queued text from the healthy reliable consumer.
    received = await drain(player)
    assert [item.payload.targets[0].output_id for item in received] == ["first", "second"]
    await output.aclose()


async def test_reliable_interrupt_overflow_fails_delivery_closed() -> None:
    output = runtime()
    await output.stream.subscribe("player", kinds=(OutputKind.CONTROL,), max_pending=1)
    await output.publish(text("first", "first"))
    await output.publish(text("second", "second"))
    await output.interrupt(output_id="first", reason="barge_in")

    with pytest.raises(ExceptionGroup) as overflowed:
        await output.interrupt(output_id="second", reason="barge_in")
    assert "interrupt queue overflowed" in str(overflowed.value.exceptions[0].__cause__)
    assert not output.accepts_run("run")
    with pytest.raises(ExceptionGroup):
        await output.aclose()


@pytest.mark.stress
async def test_back_to_back_short_outputs_keep_pcm_barriers_and_retention_exact(
    stress_seconds: float,
) -> None:
    output = runtime(output_max_records=8, output_retired_records=8)
    player = await output.stream.subscribe("player", kinds=(OutputKind.AUDIO_FRAME,), max_pending=4)
    captions = await output.stream.subscribe(
        "captions", kinds=(OutputKind.ALIGNMENT,), max_pending=2, reliable=False
    )
    played: dict[str, list[int]] = {}
    shown = 0

    async def play() -> None:
        while True:
            event = (await player.get()).output
            played.setdefault(event.output_id, []).append(event.payload.data[0])

    async def caption() -> None:
        nonlocal shown
        while True:
            await captions.get()
            shown += 1
            for _ in range(3):
                await asyncio.sleep(0)  # A slow presentation consumer.

    consumers = [asyncio.create_task(play()), asyncio.create_task(caption())]
    deadline, rounds, frames = time.monotonic() + stress_seconds, 0, 0
    while rounds < 32 or time.monotonic() < deadline:
        run, output_id, size = f"run-{rounds}", f"speech-{rounds}", 1 + rounds % 5
        output.activate_run(run)
        await output.publish(text(output_id, "hi.", run=run, mode=OutputTextMode.AUDIO_SYNCED))
        for index in range(size):
            last = (await output.publish(pcm(output_id, index, run=run))).sequence
            await output.publish(aligned(output_id, index, run=run))
        frames += size
        completed = await output.finish_audio(
            output_id=output_id, lane=OutputLane.ASSISTANT, turn_id="turn"
        )
        assert completed.output.payload.barrier.last_audio_sequence == last
        await output.complete(lane=OutputLane.ASSISTANT, output_id=output_id, turn_id="turn")
        await wait_until(
            lambda key=output_id, size=size: len(played.get(key, ())) == size, "player lost PCM"
        )
        assert played.pop(output_id) == list(range(size))
        final = OutputTranscriptChunk("", is_final=True)
        await output.publish(content(output_id, OutputKind.TRANSCRIPT_CHUNK, final, run=run))
        await output.publish(playback(output_id, OutputPlaybackType.FINISHED, 0.01, run=run))
        rounds += 1
    for task in consumers:
        task.cancel()
    await asyncio.gather(*consumers, return_exceptions=True)
    # Settled outputs were compacted: more rounds than record capacity never exhausted state.
    assert rounds > 8 and shown + captions.dropped_count <= frames
    print(f"synthetic output stress: rounds={rounds} frames={frames} captions_shown={shown}")
    await output.aclose()
