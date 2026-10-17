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

import json
import logging
import os
import re
import socket
from collections.abc import Mapping
from itertools import islice
from typing import Any

from .diagnostics import format_error
from .records import LOG_ENDPOINT_ENV, MAX_TEXT_CHARS, LogEntry, Redactor, clean

# Diagnostic formatting must not allocate an arbitrarily padded field on a producer loop.
_UNBOUNDED_FORMAT = re.compile(r"%(?:\([^)]*\))?[#0 +\-]*(?:\d{5,}|\*|\d*\.(?:\d{5,}|\*))")


def _argument(value: Any, depth: int = 0) -> Any:
    if isinstance(value, str):
        return value[: MAX_TEXT_CHARS * 2]
    if value is None or type(value) in (int, float, bool):
        return value
    if depth < 2 and isinstance(value, tuple | list):
        return tuple(_argument(item, depth + 1) for item in value[:16])
    if depth < 2 and isinstance(value, Mapping):
        return {
            str(key)[:128]: _argument(item, depth + 1)
            for key, item in islice(value.items(), 16)
            if isinstance(key, str | int)
        }
    return f"<{type(value).__name__}>"


def _message(record: logging.LogRecord) -> str:
    text = (
        record.msg[: MAX_TEXT_CHARS * 2]
        if isinstance(record.msg, str)
        else str(_argument(record.msg))
    )
    try:
        if record.args:
            if _UNBOUNDED_FORMAT.search(text):
                raise ValueError("Unbounded diagnostic format")
            args = record.args
            args = (
                _argument(args)
                if isinstance(args, Mapping)
                else tuple(_argument(value) for value in args[:64])
            )
            text = text % args
    except (TypeError, ValueError, KeyError, OverflowError):
        text = "[log message could not be formatted]"
    if record.exc_info and isinstance(record.exc_info[1], BaseException):
        text += "\n" + format_error(record.exc_info[1], details=True)
    # exc_text/stack_info may contain raw exception values or source lines; never forward them.
    return text


class LogClient(logging.Handler):
    """Atomic, nonblocking datagrams; no disk, terminal writes or pickle on producer loops."""

    def __init__(self, path: str, token: str, *, level: int, third_party_level: int) -> None:
        self._ended = True
        super().__init__()
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self._socket.setblocking(False)
        self._path, self._token = path, token
        self._threshold, self._third_party_level = level, third_party_level
        self._redact = Redactor()
        self.dropped = 0
        self.total_dropped = 0
        self._saved_handlers = tuple(logging.root.handlers)
        self._saved_level = logging.root.level
        self._avatar_logger = logging.getLogger("alphaavatar")
        self._saved_avatar_level = self._avatar_logger.level
        self._ended = False
        logging.root.handlers[:] = [self]
        logging.root.setLevel(min(level, third_party_level))
        self._avatar_logger.setLevel(level)

    def refresh(self, *, level: int | None = None, third_party_level: int | None = None) -> None:
        self._redact.refresh()
        if level is not None:
            self._threshold = level
            self._avatar_logger.setLevel(level)
        if third_party_level is not None:
            self._third_party_level = third_party_level
        logging.root.setLevel(min(self._threshold, self._third_party_level))

    def emit(self, record: logging.LogRecord) -> None:
        if self._ended:
            return
        threshold = (
            self._threshold if record.name.startswith("alphaavatar") else self._third_party_level
        )
        if record.levelno < threshold:
            return
        try:
            path = record.pathname.replace("\\", "/")
            source = (
                path.split("/alphaavatar/", 1)[-1] if "/alphaavatar/" in path else record.filename
            )
            entry = LogEntry(
                created=record.created,
                level=record.levelno,
                logger=clean(record.name, 240).replace("\n", "?"),
                source=clean(source, 240).replace("\n", "?"),
                line=record.lineno,
                pid=os.getpid(),
                process=clean(record.processName, 110).replace("\n", "?"),
                text=self._redact(_message(record)),
                dropped=self.dropped,
            )
            self._socket.sendto(entry.encode(self._token), self._path)
            self.dropped = 0
        except Exception:
            # Diagnostic failure must not fail a model, media or tool operation.
            self.dropped += 1
            self.total_dropped += 1

    def close(self) -> None:
        if self._ended:
            return
        if self.dropped:
            record = logging.LogRecord(
                "alphaavatar.log",
                logging.WARNING,
                __file__,
                0,
                "Diagnostic log records were dropped before shutdown",
                (),
                None,
            )
            self.emit(record)
        self._ended = True
        if self in logging.root.handlers:
            logging.root.handlers[:] = self._saved_handlers
            logging.root.setLevel(self._saved_level)
            self._avatar_logger.setLevel(self._saved_avatar_level)
        self._socket.close()
        super().close()


def configure_from_env() -> LogClient | None:
    raw = os.getenv(LOG_ENDPOINT_ENV)
    if raw is None:
        return None
    if len(raw) > 4096:
        raise ValueError("Invalid logging endpoint configuration")
    data = json.loads(raw)
    if not isinstance(data, dict) or set(data) != {"path", "token", "level", "third_party_level"}:
        raise ValueError("Invalid logging endpoint fields")
    if not isinstance(data["path"], str) or not os.path.isabs(data["path"]):
        raise ValueError("Logging endpoint must be absolute")
    if not isinstance(data["token"], str) or len(data["token"]) != 64:
        raise ValueError("Invalid logging endpoint credential")
    if any(
        type(data[key]) is not int or data[key] not in (10, 20, 30, 40, 50)
        for key in ("level", "third_party_level")
    ):
        raise ValueError("Invalid logging level")
    return LogClient(**data)
