# Copyright 2025 AlphaAvatar project
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
import inspect
from collections.abc import Callable, Coroutine, Iterable, MutableSequence
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from livekit.agents import ChatItem

from .context_manager import ContextManager
from .enum.op import OpType

if TYPE_CHECKING:
    from ..engine import AvatarEngine

T = TypeVar("T")


OnChange = Callable[["ObservableList[T]", OpType, dict[str, Any]], Coroutine[Any, Any, None] | None]


class ObservableList(MutableSequence, Generic[T]):
    def __init__(self, iterable: Iterable[ChatItem] = (), on_change: OnChange | None = None):
        self._list: list[ChatItem] = list(iterable)
        self._listeners: list[OnChange] = []
        if on_change:
            self._listeners.append(on_change)
        self._mute_depth = 0
        self._batch_depth = 0
        self._batched: list[tuple[str, dict[str, Any]]] = []
        self._pending_tasks: set[asyncio.Task[Any]] = set()

    def __len__(self):
        return len(self._list)

    def __getitem__(self, i):
        return self._list[i]

    def __setitem__(self, i, v) -> None:
        if isinstance(i, slice):
            old = self._list[i]
            self._list[i] = list(v)
            self._notify(OpType.SETITEM, {"index": i, "old": list(old), "new": list(v)})
        else:
            old = self._list[i]
            self._list[i] = v
            self._notify(OpType.SETITEM, {"index": i, "old": old, "new": v})

    def __delitem__(self, i) -> None:
        if isinstance(i, slice):
            old = self._list[i]
            del self._list[i]
            self._notify(OpType.DELITEM, {"index": i, "old": list(old)})
        else:
            old = self._list[i]
            del self._list[i]
            self._notify(OpType.DELITEM, {"index": i, "old": old})

    def insert(self, index: int, value: ChatItem) -> None:
        self._list.insert(index, value)
        self._notify(OpType.INSERT, {"index": index, "value": value})

    def append(self, value: ChatItem) -> None:
        idx = len(self._list)
        self._list.append(value)
        self._notify(OpType.APPEND, {"index": idx, "value": value})

    def extend(self, values: Iterable[ChatItem]) -> None:
        items = list(values)
        if not items:
            return
        start = len(self._list)
        self._list.extend(items)
        self._notify(OpType.EXTEND, {"start": start, "items": items})

    def clear(self) -> None:
        if not self._list:
            return
        old = self._list.copy()
        self._list.clear()
        self._notify(OpType.CLEAR, {"old": old})

    def pop(self, index: int = -1) -> ChatItem:
        val = self._list.pop(index)
        self._notify(OpType.POP, {"index": index, "value": val})
        return val

    def sort(self, *args, **kwargs) -> None:
        self._list.sort(*args, **kwargs)
        self._notify(OpType.SORT, {})

    def reverse(self) -> None:
        self._list.reverse()
        self._notify(OpType.REVERSE, {})

    def __iadd__(self, other: Iterable[ChatItem]):
        self.extend(other)
        return self

    def subscribe(self, fn: OnChange):
        self._listeners.append(fn)

        def off():
            try:
                self._listeners.remove(fn)
            except ValueError:
                pass

        return off

    @contextmanager
    def muted(self):
        self._mute_depth += 1
        try:
            yield
        finally:
            self._mute_depth -= 1

    @contextmanager
    def batch(self):
        self._batch_depth += 1
        try:
            yield
        finally:
            self._batch_depth -= 1
            if self._batch_depth == 0 and self._batched:
                events = self._batched
                self._batched = []
                self._emit(OpType.BATCH, {"events": events})

    def _notify(self, op: OpType, payload: dict[str, Any]) -> None:
        if self._batch_depth > 0:
            self._batched.append((op, payload))
            return
        self._emit(op, payload)

    def _emit(self, op: OpType, payload: dict[str, Any]) -> None:
        if self._mute_depth > 0:
            return

        for fn in list(self._listeners):
            try:
                result = fn(self, op, payload)
            except Exception:
                # TODO: log
                raise

            if inspect.isawaitable(result):
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    asyncio.run(result)
                else:
                    task = loop.create_task(result)
                    self._pending_tasks.add(task)

                    def _cleanup(t: asyncio.Task[Any]):
                        self._pending_tasks.discard(t)
                        _ = t.exception()

                    task.add_done_callback(_cleanup)

    async def wait_pending(self) -> None:
        if self._pending_tasks:
            await asyncio.gather(*list(self._pending_tasks), return_exceptions=False)


def init_context_manager(engine: AvatarEngine):
    context_manager = ContextManager(engine=engine)

    if not isinstance(engine._chat_ctx.items, ObservableList):
        engine._chat_ctx.items = ObservableList(engine._chat_ctx.items, on_change=context_manager)  # type: ignore[assignment]
    else:
        engine._chat_ctx.items.subscribe(context_manager)
