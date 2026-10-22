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

import io
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr, redirect_stdout


class _LogStream(io.TextIOBase):
    def __init__(self, level: int, *, limit: int = 2048) -> None:
        if limit < 1:
            raise ValueError("Capture line limit must be positive")
        self._level, self._limit = level, limit
        self._buffer = ""
        self._origin: tuple[str, str, int] | None = None

    def writable(self) -> bool:
        return True

    def write(self, value: str) -> int:
        if not isinstance(value, str):
            raise TypeError("Text capture requires text")
        frame = sys._getframe(1)
        try:
            origin = (
                frame.f_globals.get("__name__", "inference"),
                frame.f_code.co_filename,
                frame.f_lineno,
            )
        finally:
            del frame
        # print() can split a line into many writes. Never retain an unbounded partial line.
        for chunk in value.splitlines(keepends=True):
            while chunk:
                if not self._buffer:
                    self._origin = origin
                take = min(len(chunk), self._limit - len(self._buffer))
                self._buffer += chunk[:take]
                chunk = chunk[take:]
                if self._buffer.endswith(("\n", "\r")) or len(self._buffer) >= self._limit:
                    self.flush()
        return len(value)

    def flush(self) -> None:
        text, self._buffer = self._buffer.rstrip("\r\n"), ""
        if text and self._origin is not None:
            module, path, line = self._origin
            logger = logging.getLogger("alphaavatar.inference.capture")
            record = logger.makeRecord(logger.name, self._level, path, line, text, (), None)
            record.name = "alphaavatar.inference.capture." + str(module)
            logger.handle(record)
        self._origin = None


@contextmanager
def capture_initialization_output() -> Iterator[None]:
    """Python streams only, scoped to synchronous initialization in an isolated runner."""
    stdout, stderr = _LogStream(logging.INFO), _LogStream(logging.WARNING)
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            yield
    finally:
        stdout.flush()
        stderr.flush()
