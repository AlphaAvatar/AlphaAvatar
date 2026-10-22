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
import math
import threading
from collections.abc import Coroutine
from concurrent.futures import Future
from typing import Any


class AsyncLoopThread:
    """An owned async loop for synchronous inference workers, never a realtime-loop bridge."""

    def __init__(self, name: str = "async-loop") -> None:
        self._require_sync()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._error: BaseException | None = None
        self._closing = False
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._thread.start()
        self._ready.wait()
        if self._error is not None:
            self._thread.join()
            raise RuntimeError("Async worker loop could not start") from self._error

    @staticmethod
    def _require_sync() -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        raise RuntimeError("Blocking loop-thread operations are not allowed on an event loop")

    def _run(self) -> None:
        loop = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            self._ready.set()
            loop.run_forever()
        except BaseException as error:
            self._error = error
            self._ready.set()
        finally:
            with self._lock:
                self._closing = True
            if loop is not None:
                try:
                    pending = tuple(asyncio.all_tasks(loop))
                    for task in pending:
                        task.cancel()
                    if pending:
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    loop.run_until_complete(loop.shutdown_asyncgens())
                    loop.run_until_complete(loop.shutdown_default_executor())
                except BaseException as error:
                    self._error = error
                finally:
                    asyncio.set_event_loop(None)
                    loop.close()

    def submit_future(self, coro: Coroutine[Any, Any, Any]) -> Future:
        with self._lock:
            if self._closing or self._loop is None:
                coro.close()
                raise RuntimeError("Async worker loop is closing or closed")
            try:
                return asyncio.run_coroutine_threadsafe(coro, self._loop)
            except BaseException:
                coro.close()
                raise

    def submit(self, coro: Coroutine[Any, Any, Any], timeout: float | None = None) -> Any:
        try:
            self._require_sync()
            if timeout is not None and (not math.isfinite(timeout) or timeout <= 0):
                raise ValueError("Async worker deadline must be finite and positive")
        except BaseException:
            coro.close()
            raise

        started = False

        async def execute():
            nonlocal started
            started = True
            async with asyncio.timeout(timeout):
                return await coro

        work = execute()
        try:
            future = self.submit_future(work)
        except BaseException:
            coro.close()
            raise

        def release_unstarted(_):
            if not started:
                coro.close()

        future.add_done_callback(release_unstarted)
        # The async deadline cancels and settles the operation before this returns.
        # Future.result(timeout=...) alone would leave the remote work running.
        return future.result()

    def stop(self, timeout: float = 10.0) -> None:
        self._require_sync()
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Async worker shutdown timeout must be finite and positive")
        with self._lock:
            if not self._closing:
                self._closing = True
                if self._loop is not None:
                    self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise RuntimeError("Async worker loop did not finish cleanup before its deadline")
        if self._error is not None:
            raise RuntimeError("Async worker loop shutdown failed") from self._error
