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


class ProcessGroup:
    """A dedicated POSIX process group, not containment for descendants which detach."""

    def __init__(self, pid: int) -> None:
        self.require_supported()
        if pid <= 1 or pid == os.getpgrp():
            raise ValueError("Execution process group must be separate from the Host")
        self.pid = pid
        self._empty = False

    @staticmethod
    def require_supported() -> None:
        if os.name != "posix":
            raise RuntimeError("Hosted execution requires POSIX process groups on this platform")

    @property
    def empty(self) -> bool:
        if not self._empty:
            try:
                os.killpg(self.pid, 0)
            except ProcessLookupError:
                # Never signal this numeric group again after observing its disappearance.
                self._empty = True
            except OSError:
                return False
        return self._empty

    def signal(self, value: signal.Signals) -> None:
        if self.empty:
            return
        if self.pid == os.getpgrp():
            raise RuntimeError("Refusing to signal the Host process group")
        try:
            os.killpg(self.pid, value)
        except ProcessLookupError:
            self._empty = True
