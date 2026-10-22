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
import logging
from collections.abc import AsyncIterator, Callable

from alphaavatar.agents.avatar.provider.base import StreamingLLMBase
from alphaavatar.agents.avatar.provider.errors import ModelProtocolError
from alphaavatar.agents.avatar.provider.schemas import ModelRequest
from alphaavatar.agents.avatar.provider.schemas.stream import (
    ModelResponseCompleted,
    ModelStreamEvent,
)
from alphaavatar.core.cleanup import wait_for_cleanup

logger = logging.getLogger(__name__)


class ProviderStream(AsyncIterator[ModelStreamEvent]):
    """A bounded per-request producer. Its control/close path never waits for queue space."""

    def __init__(
        self,
        model: StreamingLLMBase,
        request: ModelRequest,
        report: Callable[[str, ModelResponseCompleted | None, BaseException | None], None],
    ) -> None:
        self._report = report
        self._queue: asyncio.Queue[ModelStreamEvent] = asyncio.Queue(maxsize=64)
        self._closed = False
        self._reading = False
        self._failure_observed = False
        self._close_task: asyncio.Task[None] | None = None
        self.task = asyncio.create_task(
            self._produce(model, request), name=f"provider_stream:{request.request_id}"
        )
        self.task.add_done_callback(self._observe)

    @staticmethod
    def _observe(task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()

    async def _produce(self, model: StreamingLLMBase, request: ModelRequest) -> None:
        terminal = None
        response_id = None
        status = "failed"
        failure = None
        try:
            async with model.stream(request) as events:
                async for event in events:
                    if terminal is not None:
                        raise ModelProtocolError("Provider emitted an event after completion")
                    if event.request_id != request.request_id:
                        raise ModelProtocolError("Provider stream request identity changed")
                    if response_id is not None and event.response_id != response_id:
                        raise ModelProtocolError("Provider response identity changed")
                    response_id = event.response_id
                    if isinstance(event, ModelResponseCompleted):
                        terminal = event
                    else:
                        await self._queue.put(event)
            if terminal is None:
                raise ModelProtocolError("Provider stream ended without completion")
            # No success escapes until the backend has released its request resources.
            await self._queue.put(terminal)
            status = "success"
        except asyncio.CancelledError as exc:
            status, failure = "cancelled", exc
            raise
        except BaseException as exc:
            failure = exc
            raise
        finally:
            try:
                self._report(status, terminal, failure)
            except Exception:
                logger.exception("Provider stream diagnostic recording failed")

    def _check_failure(self) -> None:
        if self.task.done():
            try:
                self.task.result()
            except BaseException:
                self._failure_observed = True
                raise

    async def __anext__(self) -> ModelStreamEvent:
        if self._reading:
            raise RuntimeError("A Provider stream cannot have concurrent readers")
        if self._closed:
            raise StopAsyncIteration
        self._reading = True
        get = None
        try:
            self._check_failure()
            try:
                return self._queue.get_nowait()
            except asyncio.QueueEmpty:
                if self.task.done():
                    raise StopAsyncIteration from None
            get = asyncio.create_task(self._queue.get(), name="provider_stream_read")
            await asyncio.wait((get, self.task), return_when=asyncio.FIRST_COMPLETED)
            self._check_failure()
            if get.done():
                return get.result()
            try:
                return self._queue.get_nowait()
            except asyncio.QueueEmpty:
                raise StopAsyncIteration from None
        finally:
            if get is not None:
                if not get.done():
                    get.cancel()
                await asyncio.gather(get, return_exceptions=True)
            self._reading = False

    async def _close(self) -> None:
        self._closed = True
        if not self.task.done():
            self.task.cancel()
        result = (await asyncio.gather(self.task, return_exceptions=True))[0]
        while not self._queue.empty():
            self._queue.get_nowait()
        if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
            if not self._failure_observed:
                self._failure_observed = True
                raise result

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="provider_stream_release")
        await wait_for_cleanup(self._close_task)
