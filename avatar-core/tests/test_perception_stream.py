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
from __future__ import annotations

import asyncio

import pytest

from alphaavatar.core.perception.enums import PerceptionStreamKind
from alphaavatar.core.perception.stream import PerceptionStream


def video_stream(maxlen: int = 4) -> PerceptionStream[int]:
    return PerceptionStream(name=PerceptionStreamKind.VIDEO, maxlen=maxlen)


def test_slow_consumer_never_blocks_publisher_and_sees_an_explicit_gap() -> None:
    frames = video_stream(maxlen=4)
    for value in range(10):
        frames.publish(value)
    read = frames.read_pending(consumer_id="vision")
    assert read.items == [6, 7, 8, 9]
    assert read.missed_count == 6 and read.has_gap
    frames.commit(consumer_id="vision", cursor_seq=read.cursor_seq)
    assert frames.get_consumer_lag("vision") == 0


def test_consumer_cursors_are_independent_and_monotonic() -> None:
    frames = video_stream()
    for value in range(3):
        frames.publish(value)
    frames.commit(consumer_id="audio", cursor_seq=2)
    frames.commit(consumer_id="audio", cursor_seq=1)
    assert frames.get_consumer_cursor("audio") == 2
    assert frames.read_pending(consumer_id="video").items == [0, 1, 2]
    assert frames.read_pending(consumer_id="audio").items == [2]
    with pytest.raises(ValueError, match="future cursor"):
        frames.commit(consumer_id="audio", cursor_seq=4)


async def test_wait_for_pending_wakes_on_publish_and_times_out_without_data() -> None:
    frames = video_stream()
    assert await frames.wait_for_pending(consumer_id="turn", timeout=0.01) is False
    waiter = asyncio.create_task(frames.wait_for_pending(consumer_id="turn", timeout=30))
    await asyncio.sleep(0)
    frames.publish(1)
    async with asyncio.timeout(5):
        assert await waiter is True
