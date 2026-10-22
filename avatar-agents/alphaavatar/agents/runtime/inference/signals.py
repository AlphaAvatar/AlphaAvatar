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

import os
import signal
from multiprocessing import resource_tracker
from multiprocessing.process import BaseProcess


def start_runner_process(process: BaseProcess) -> None:
    """Protect spawn bootstrap without changing the Host's process-wide SIGINT handler."""
    if os.name != "posix":
        process.start()
        return
    # CPython 3.11's first tracker launch unblocks SIGINT internally. Start that helper
    # before masking the launching thread; never patch multiprocessing signal handlers.
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, set())
    try:
        resource_tracker.ensure_running()
        signal.pthread_sigmask(signal.SIG_SETMASK, previous | {signal.SIGINT})
        process.start()
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def configure_runner_signals() -> None:
    # The Host owns Ctrl+C. Runner shutdown arrives through CLOSE; SIGTERM remains
    # available to the runner process owner for forced reclamation.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    if os.name == "posix":
        signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT, signal.SIGTERM})
