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
import re


class ExecutionStop:
    """Latch the first stop request without replacing the execution's final outcome."""

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._reason = ""

    @property
    def reason(self) -> str:
        return self._reason

    def is_set(self) -> bool:
        return self._event.is_set()

    def request(self, reason: str) -> None:
        if not isinstance(reason, str) or re.fullmatch(r"[a-zA-Z0-9_:.-]{1,128}", reason) is None:
            raise ValueError("Invalid execution stop reason")
        if not self._event.is_set():
            self._reason = reason
            self._event.set()

    async def wait(self) -> None:
        await self._event.wait()
