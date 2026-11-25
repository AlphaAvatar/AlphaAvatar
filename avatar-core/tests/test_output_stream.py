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
"""OutputStream queue semantics only; these do not measure transport or playback timing."""

from __future__ import annotations

import asyncio
from itertools import count

import pytest

from alphaavatar.core.env.output import EnvOutput
from alphaavatar.core.output import OutputStream, OutputSubscription
from alphaavatar.core.output.enums import OutputControlType, OutputKind, OutputLane
from alphaavatar.core.output.schemas import (
    OutputControl,
    OutputEvent,
    OutputIdentity,
    OutputScope,
    OutputSource,
    OutputTextChunk,
)

SCOPE = OutputScope(context_id="context", turn_id="turn")
SOURCE = OutputSource(producer="test")
_sequence = count(1)


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


def publication(output: EnvOutput) -> OutputEvent:
    sequence = next(_sequence)
    return OutputEvent(
        event_id=f"event-{sequence}",
        sequence=sequence,
        session_id="session",
        created_at=float(sequence),
        monotonic_ns=sequence,
        output=output,
    )


def text(value: str) -> OutputEvent:
    return publication(
        EnvOutput(
            kind=OutputKind.TEXT_CHUNK,
            lane=OutputLane.ASSISTANT,
            scope=SCOPE,
            source=SOURCE,
            payload=OutputTextChunk(text=value),
            output_id="output",
        )
    )


def interrupt() -> OutputEvent:
    target = OutputIdentity(output_id="output", lane=OutputLane.ASSISTANT, scope=SCOPE)
    return publication(
        EnvOutput(
            kind=OutputKind.CONTROL,
            lane=OutputLane.ASSISTANT,
            scope=None,
            source=SOURCE,
            payload=OutputControl(
                type=OutputControlType.INTERRUPT, reason="barge_in", targets=(target,)
            ),
        )
    )


async def texts(subscription: OutputSubscription, size: int) -> list[str]:
    return [(await subscription.get()).output.payload.text for _ in range(size)]


async def test_interrupt_bypasses_full_reliable_queue_and_blocked_publisher() -> None:
    stream = OutputStream()
    player = await stream.subscribe("player", max_pending=1)
    await stream.publish(text("a"))
    blocked = asyncio.create_task(stream.publish(text("b")))
    await settle()
    assert not blocked.done()

    async with asyncio.timeout(5):
        await stream.publish(interrupt())
    assert (await player.get()).output.kind == OutputKind.CONTROL
    assert await texts(player, 2) == ["a", "b"]
    async with asyncio.timeout(5):
        await blocked
    await stream.aclose()


async def test_unreliable_subscriber_drops_oldest_and_never_blocks_publisher() -> None:
    stream = OutputStream()
    captions = await stream.subscribe("captions", max_pending=2, reliable=False)
    player = await stream.subscribe("player", max_pending=8)
    async with asyncio.timeout(5):
        for value in "abcde":
            await stream.publish(text(value))
    assert captions.dropped_count == 3
    assert await texts(captions, 2) == ["d", "e"]
    assert await texts(player, 5) == list("abcde")
    await stream.aclose()


async def test_fail_fast_overflow_retires_only_the_slow_subscriber() -> None:
    stream = OutputStream()
    slow = await stream.subscribe("slow", max_pending=1, fail_on_overflow=True)
    healthy = await stream.subscribe("healthy", max_pending=8)
    await stream.publish(text("a"))
    with pytest.raises(ExceptionGroup) as raised:
        await stream.publish(text("b"))
    (failure,) = raised.value.exceptions
    assert "'slow' failed" in str(failure) and "'slow' overflowed" in str(failure.__cause__)
    with pytest.raises(RuntimeError, match="'slow' failed"):
        await slow.get()
    assert await texts(healthy, 2) == ["a", "b"]
    await stream.aclose()


async def test_cancelled_publisher_reaps_its_fanout_tasks() -> None:
    stream = OutputStream()
    await stream.subscribe("full", max_pending=1)
    await stream.subscribe("open", max_pending=8)
    await stream.publish(text("a"))
    before = asyncio.all_tasks()
    publisher = asyncio.create_task(stream.publish(text("b")))
    await settle()
    fanout = {
        task
        for task in asyncio.all_tasks() - before
        if task.get_coro().__qualname__ == "OutputSubscription.push"
    }
    # The open subscriber accepted immediately; only the push into the full queue is pending.
    assert len(fanout) == 1 and not publisher.done()

    publisher.cancel()
    with pytest.raises(asyncio.CancelledError):
        await publisher
    # Checked before aclose(): closing the stream would release a blocked push by itself.
    assert all(task.cancelled() for task in fanout)
    assert asyncio.all_tasks() - before == set()
    await stream.aclose()
