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
import signal
from collections.abc import Callable, Iterator
from contextlib import contextmanager


@contextmanager
def shutdown_signals(request_stop: Callable[[], None]) -> Iterator[None]:
    loop = asyncio.get_running_loop()
    installed = []
    requested = False

    def stop(signum: int) -> None:
        nonlocal requested
        if not requested:
            requested = True
            logging.getLogger(__name__).info(
                "Shutdown requested signal=%s", signal.Signals(signum).name
            )
            request_stop()

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous = signal.getsignal(signum)
            try:
                loop.add_signal_handler(signum, stop, signum)
            except NotImplementedError:
                signal.signal(signum, lambda received, _: loop.call_soon_threadsafe(stop, received))
            installed.append((signum, previous))
        yield
    finally:
        for signum, previous in installed:
            try:
                loop.remove_signal_handler(signum)
            except NotImplementedError:
                pass
            signal.signal(signum, previous)
