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
import math
import os
import re
from dataclasses import asdict, dataclass, field
from urllib.parse import urlsplit, urlunsplit

from .events import LABELS, MAX_CONTENT_CHARS, validate_fields

MAX_PACKET_BYTES = 60_000
MAX_TEXT_CHARS = 8192
LOG_ENDPOINT_ENV = "ALPHAAVATAR_LOG_ENDPOINT"

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")
_ANSI = re.compile(r"\x1b(?:\][^\x07\x1b]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~])")
_SECRET_KEY = re.compile(
    r"(?i)(?:token|secret|password|passwd|api[_-]?key|authorization|credential)"
)
_SECRET_PAIR = re.compile(
    r"(?i)((?:[\w-]*(?:token|secret|password|passwd|api[_-]?key|authorization|credential))"
    r"[\"']?\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|(?:Bearer|Basic)\s+[^\s,;]+|[^\s,;&]+)"
)
_AUTH = re.compile(r"(?i)\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+")
_URL = re.compile(r"(?i)(?:https?|wss?)://[^\s'\"<>]+")
_COOKIE = re.compile(r"(?i)((?<![\w-])(?:set-)?cookie[\"']?[ \t]*[:=][ \t]*)[^\r\n]*")
_MCP_SESSION = re.compile(
    r"(?i)((?<![\w-])mcp[-_ ]session[-_ ]id[\"']?[ \t]*[:=][ \t]*)"
    r"(?:\[redacted\]|\"[^\"\r\n]*\"?|'[^'\r\n]*'?|[^\s,;]+)"
)
_SESSION = re.compile(
    r"(?i)((?<![\w-])session[-_ ]?id[\"']?[ \t]*[:=][ \t]*)"
    r"(?:\[redacted\]|\"[^\"\r\n]*\"?|'[^'\r\n]*'?|[^\s,;]+)"
)


def clean(value: str, limit: int = MAX_TEXT_CHARS) -> str:
    value = _ANSI.sub("", value)
    value = _CONTROL.sub("?", value.replace("\r", "\\r"))
    return value if len(value) <= limit else value[:limit] + " [truncated]"


def _redact_url(match: re.Match[str]) -> str:
    try:
        parts = urlsplit(match[0])
        return urlunsplit((parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path, "", ""))
    except ValueError:
        return "[redacted URL]"


class Redactor:
    """Best-effort credential filtering, not a guarantee that opted-in text is free of PII."""

    def __init__(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        values = {
            value
            for key, value in os.environ.items()
            if _SECRET_KEY.search(key) and 4 <= len(value) <= 4096
        }
        self._secrets = tuple(sorted(values, key=len, reverse=True))

    def __call__(self, text: str, *, logger: str = "") -> str:
        # Bound work before regex processing, retaining enough input to mask boundary values.
        truncated = len(text) > MAX_TEXT_CHARS * 2
        text = text[: MAX_TEXT_CHARS * 2]
        for secret in self._secrets:
            text = text.replace(secret, "[redacted]")
        text = _URL.sub(_redact_url, text)
        text = _SECRET_PAIR.sub(lambda match: match[1] + "[redacted]", text)
        text = _AUTH.sub("[redacted authorization]", text)
        text = _COOKIE.sub(lambda match: match[1] + "[redacted]", text)
        text = _MCP_SESSION.sub(lambda match: match[1] + "[redacted]", text)
        origin = logger.removeprefix("alphaavatar.inference.capture.")
        if origin in ("mcp", "alphaavatar.plugins.mcp") or origin.startswith(
            ("mcp.", "alphaavatar.plugins.mcp.")
        ):
            text = _SESSION.sub(lambda match: match[1] + "[redacted]", text)
        return clean(text + (" [truncated]" if truncated else ""))


@dataclass(frozen=True, slots=True)
class LogEntry:
    created: float
    level: int
    logger: str
    source: str
    line: int
    pid: int
    process: str
    text: str
    dropped: int = 0
    event: str | None = None
    fields: dict = field(default_factory=dict)
    content: str | None = None
    content_truncated: bool = False

    def encode(self, token: str) -> bytes:
        payload = json.dumps(
            {"token": token, "entry": asdict(self)},
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(payload) > MAX_PACKET_BYTES:
            raise ValueError("Log entry exceeds the transport limit")
        return payload

    @classmethod
    def decode(cls, payload: bytes, token: str) -> LogEntry:
        import secrets

        if len(payload) > MAX_PACKET_BYTES:
            raise ValueError("Log packet exceeds its limit")
        data = json.loads(payload)
        if not isinstance(data, dict) or set(data) != {"token", "entry"}:
            raise ValueError("Invalid log packet")
        supplied = data["token"]
        if not isinstance(supplied, str) or not secrets.compare_digest(supplied, token):
            raise ValueError("Invalid log sender")
        entry = cls(**data["entry"])
        if type(entry.created) not in (float, int) or not math.isfinite(entry.created):
            raise ValueError("Invalid log timestamp")
        if not 0 <= entry.created <= 253402300799:
            raise ValueError("Log timestamp is outside the supported range")
        for value, low, high in (
            (entry.level, 0, 100),
            (entry.line, 0, 10_000_000),
            (entry.pid, 1, 2**32),
            (entry.dropped, 0, 2**63 - 1),
        ):
            if type(value) is not int or not low <= value <= high:
                raise ValueError("Invalid log counter")
        for value, maximum in (
            (entry.logger, 256),
            (entry.source, 256),
            (entry.process, 128),
            (entry.text, MAX_TEXT_CHARS + 32),
        ):
            if not isinstance(value, str) or len(value) > maximum:
                raise ValueError("Invalid log text")
        validate_fields(entry.fields)
        if entry.event is not None and entry.event not in LABELS:
            raise ValueError("Invalid conversation event")
        if entry.event is None and (entry.fields or entry.content is not None):
            raise ValueError("Conversation data requires an event")
        if entry.content is not None and (
            type(entry.content) is not str or len(entry.content) > MAX_CONTENT_CHARS
        ):
            raise ValueError("Invalid conversation content")
        if type(entry.content_truncated) is not bool:
            raise ValueError("Invalid conversation truncation flag")
        return entry
