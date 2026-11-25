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

from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.lifecycle import (
    LifecycleComponent,
    LifecycleError,
    LifecycleGroup,
    LifecyclePhase,
)


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


class Component(LifecycleComponent):
    def __init__(
        self,
        name: str,
        events: list[str],
        *,
        fail: bool = False,
        release: asyncio.Event | None = None,
    ) -> None:
        self.name, self.events, self.fail, self.release = name, events, fail, release

    async def on_start(self) -> None:
        self.events.append(f"start:{self.name}")
        if self.release is not None:
            await self.release.wait()
        if self.fail:
            raise ValueError(self.name)

    async def on_stop(self) -> None:
        self.events.append(f"stop:{self.name}")


async def test_cancelled_caller_waits_for_owned_cleanup() -> None:
    release = asyncio.Event()
    cleanup = asyncio.create_task(release.wait())
    caller = asyncio.create_task(wait_for_cleanup(cleanup))
    await settle()
    caller.cancel()
    await settle()
    assert not caller.done()

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert cleanup.done() and not cleanup.cancelled()


async def test_phases_start_in_order_and_stop_in_reverse() -> None:
    events: list[str] = []
    group = LifecycleGroup(
        [
            LifecyclePhase.create("transport", [Component("rtc", events)]),
            LifecyclePhase.create("runtime", [Component("loop", events)]),
        ]
    )
    await group.start()
    await group.stop()
    assert events == ["start:rtc", "start:loop", "stop:loop", "stop:rtc"]


async def test_start_failure_stops_every_owned_component_in_reverse() -> None:
    events: list[str] = []
    group = LifecycleGroup(
        [
            LifecyclePhase.create("transport", [Component("rtc", events)]),
            LifecyclePhase.create("runtime", [Component("loop", events, fail=True)]),
            LifecyclePhase.create("diagnostics", [Component("unstarted", events)]),
        ]
    )
    with pytest.raises(ExceptionGroup) as raised:
        await group.start()
    assert raised.group_contains(LifecycleError, match="'runtime'")
    # Components whose start never ran still release partial or unstarted state.
    assert events == ["start:rtc", "start:loop", "stop:unstarted", "stop:loop", "stop:rtc"]


async def test_cancelled_start_converges_to_a_stopped_single_use_group() -> None:
    events: list[str] = []
    release = asyncio.Event()
    group = LifecycleGroup(
        [LifecyclePhase.create("runtime", [Component("model", events, release=release)])]
    )
    starting = asyncio.create_task(group.start())
    await settle()
    starting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await starting
    assert events == ["start:model", "stop:model"]
    with pytest.raises(RuntimeError, match="stopping or stopped"):
        await group.start()
