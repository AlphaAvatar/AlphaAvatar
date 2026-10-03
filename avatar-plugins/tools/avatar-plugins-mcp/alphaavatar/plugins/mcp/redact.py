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
"""Redaction of credentials from MCP logs and from URLs shown to the model."""

from __future__ import annotations

import logging
import re
import traceback
from urllib.parse import urlsplit, urlunsplit

MASK = "***"

_KEY = (
    r"(?<![A-Za-z0-9])(?:[A-Za-z0-9]+[_-])*"
    r"(?:authorization|token|secret|password|passwd|api[_-]?key|apikey|credential|private[_-]?key)"
)

# Cookie headers hold several "k=v; k=v" pairs, so mask to the end of the line.
_COOKIE_RE = re.compile(r"(?i)((?<![A-Za-z0-9])(?:set-)?cookie[\"']?\s*[:=]\s*)[^\r\n]*")

# key=value, key: value, "key": "value" with an optional auth scheme before the secret.
_KEY_VALUE_RE = re.compile(
    rf"(?i)({_KEY}[\"']?\s*[:=]\s*)"
    r"((?:Bearer|Basic|Token)\s+[^\s,;\"'}\])]+|\"[^\"]*\"|'[^']*'|[^\s,&;\"'}\])]+)"
)

_BEARER_RE = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_URL_RE = re.compile(r"https?://[^\s'\"<>]+")


def _mask_value(match: re.Match[str]) -> str:
    value = match.group(2)
    if value[:1] in {'"', "'"} and value[-1:] == value[:1] and len(value) >= 2:
        return f"{match.group(1)}{value[0]}{MASK}{value[0]}"
    return f"{match.group(1)}{MASK}"


def redact_url(url: str) -> str:
    """Drop credentials from a URL: ``user:pass@`` and every query value."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url

    netloc = parts.netloc.rsplit("@", 1)[-1] if "@" in parts.netloc else parts.netloc
    query = "&".join(
        f"{pair.split('=', 1)[0]}={MASK}" if "=" in pair else pair
        for pair in parts.query.split("&")
        if pair
    )
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


def redact_text(text: str) -> str:
    """Mask tokens, API keys, passwords, cookies, and authorization values in free text."""
    if not text:
        return text

    text = _URL_RE.sub(lambda m: redact_url(m.group(0)), text)
    text = _COOKIE_RE.sub(lambda m: f"{m.group(1)}{MASK}", text)
    text = _KEY_VALUE_RE.sub(_mask_value, text)
    return _BEARER_RE.sub(lambda m: f"{m.group(1)} {MASK}", text)


class RedactingFilter(logging.Filter):
    """Redacts the message, traceback, and stack of every record logged through a logger."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact_text(record.getMessage())
            record.args = None

            if record.exc_info:
                record.exc_text = redact_text("".join(traceback.format_exception(*record.exc_info)))
                record.exc_info = None
            elif record.exc_text:
                record.exc_text = redact_text(record.exc_text)

            if record.stack_info:
                record.stack_info = redact_text(record.stack_info)
        except Exception:
            # Never let redaction break logging, but never leak the raw record either.
            record.msg = "[log record could not be redacted]"
            record.args = None
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True
