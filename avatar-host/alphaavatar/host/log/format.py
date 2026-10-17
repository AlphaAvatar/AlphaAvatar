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

import logging
import os
from datetime import datetime
from typing import TextIO

from alphaavatar.core.log.records import LogEntry, clean

BRAND_BLUE = "\033[38;2;96;165;250m"  # Figma --color-logo-accent-primary, #60a5fa.
SIGNAL_CYAN = "\033[38;2;34;211;238m"  # Figma --alphaavatar-signal, #22d3ee.
DIM = "\033[90m"
RESET = "\033[0m"
BOLD = "\033[1m"
_LEVEL_COLORS = {
    10: DIM,
    20: "\033[32m",
    23: SIGNAL_CYAN,
    30: "\033[33m",
    40: "\033[31m",
    50: "\033[1;31m",
}


def use_color(mode: str, stream: TextIO) -> bool:
    if "NO_COLOR" in os.environ or os.getenv("TERM") == "dumb" or mode == "never":
        return False
    return mode == "always" or bool(getattr(stream, "isatty", lambda: False)())


def console_lines(entry: LogEntry, *, color: bool) -> str:
    try:
        local_time = datetime.fromtimestamp(entry.created).astimezone()
        stamp = local_time.isoformat(timespec="milliseconds")
    except (OSError, OverflowError, ValueError):
        stamp = "invalid-timestamp"
    level = "DEV" if entry.level == 23 else logging.getLevelName(entry.level)
    source = clean(entry.source, 256).replace("\n", "?")
    origin = f"{source}:{entry.line}"
    prefix = f"{stamp} {level:<8} {origin} [{entry.pid}]"
    if color:
        prefix = (
            f"{DIM}{stamp}{RESET} {_LEVEL_COLORS.get(entry.level, RESET)}{level:<8}{RESET} "
            f"{DIM}{origin} [{entry.pid}]{RESET}"
        )
    lines = clean(entry.text).split("\n")
    if len(lines) > 24:
        lines = [*lines[:23], "[additional log lines omitted]"]
    return "".join(f"{prefix}  {line}\n" for line in lines)
