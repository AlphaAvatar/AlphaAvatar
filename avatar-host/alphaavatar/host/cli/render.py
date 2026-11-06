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
"""The look config init, config check, setup and doctor share in their text reports.

A report is a title, a status, then groups of rows: labels in one column, values aligned in
the next. A value too long for the terminal goes below its label, indented and wrapped at
spaces; diagnostics print as they are, so their lines stay whole. Colors decorate text on a
terminal only: pipes, ``NO_COLOR`` and ``TERM=dumb`` get the same structure in plain text,
and JSON never comes here. Callers pass text already redacted; it is control-character
cleaned before it is styled.
"""

from __future__ import annotations

import os
import sys
import textwrap
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from alphaavatar.core.log.records import clean
from alphaavatar.host.log.format import (
    BOLD,
    BRAND_BLUE,
    DIM,
    GREEN,
    RED,
    RESET,
    SIGNAL_CYAN,
    YELLOW,
    use_color,
)

STATUSES = {"OK": GREEN, "PASS": GREEN, "WARN": YELLOW, "FAIL": RED, "ERROR": RED, "SKIP": DIM}
STATUS = 6  # A status and its gap: "ERROR " and the rest, padded alike.
GAP = 3  # Between a label and its value.
LABEL = 10  # The narrowest label column, before its gap.
STEP = 15  # A setup step's name and its gap.
# Where a stream cannot encode them, as an ASCII terminal.
_ASCII = str.maketrans({"·": "-", "→": "->", "—": "-", "…": "..."})


def _width(stream: TextIO) -> int:
    """``COLUMNS``, else the stream's own terminal, else 100: a pipe or a file has no width
    of its own, whatever terminal the process was started from."""
    try:
        if (columns := int(os.environ.get("COLUMNS", ""))) > 0:
            return columns
    except ValueError:
        pass
    try:
        if (columns := os.get_terminal_size(stream.fileno()).columns) > 0:
            return columns
    except (AttributeError, OSError, ValueError):
        pass
    return 100


def home_relative(path: str | Path) -> str:
    """A path for people to read: under the home directory, from ``~``."""
    try:
        return "~/" + str(Path(path).relative_to(Path.home()))
    except ValueError:
        return str(path)


class Report:
    """One command's text report on its stream: stdout, or stderr for what must leave
    stdout to JSON or to the command's result."""

    def __init__(self, stream: TextIO | None = None, *, width: int | None = None) -> None:
        self.stream = stream if stream is not None else sys.stdout
        self.color = use_color("auto", self.stream)
        # A terminal updates a step's line in place; a pipe or log gets each line.
        tty = bool(getattr(self.stream, "isatty", lambda: False)())
        self.live = tty and os.getenv("TERM") != "dumb"
        self.width = width or _width(self.stream)
        encoding = getattr(self.stream, "encoding", None) or "utf-8"
        try:
            "·→—…".encode(encoding)
            self._ascii = False
        except (LookupError, UnicodeEncodeError):
            self._ascii = True
        # The step in progress: shown on a terminal, on a line not yet ended; elsewhere shown
        # only once something goes under it, as a question or progress does.
        self._open: tuple[int, str] | None = None

    # Output

    def _emit(self, text: str, *, flush: bool = False) -> None:
        self.stream.write(text.translate(_ASCII) if self._ascii else text)
        if flush or self.live:  # Steps and questions show at once; a pipe buffers the rest.
            self.stream.flush()

    def _settle(self) -> None:
        """End a step's line in progress, leaving it shown, before what goes below it."""
        if self._open is not None:
            shown = "" if self.live else self.paint("{:02d}  {}".format(*self._open), SIGNAL_CYAN)
            self._emit(shown + "\n", flush=True)
            self._open = None

    def write(self, line: str = "") -> None:
        self._settle()
        self._emit(line + "\n")

    def paint(self, text: str, style: str) -> str:
        return f"{style}{text}{RESET}" if self.color and text else text

    # Parts

    def title(self, name: str) -> None:
        """``AlphaAvatar / <name>``, a blank line apart from the command line."""
        self.write()
        self.write(self.paint(f"AlphaAvatar / {name}", BRAND_BLUE))

    def label(self, status: str) -> str:
        return self.paint(status, STATUSES[status]) + " " * (STATUS - len(status))

    def status(self, status: str, message: str) -> None:
        self.write(self.label(status) + clean(message))

    def heading(self, text: str) -> None:
        self.write()
        self.write(self.paint(text, BOLD))

    @staticmethod
    def column(labels: Sequence[str]) -> int:
        """The value column for these labels."""
        return max([LABEL, *map(len, labels)]) + GAP

    def row(
        self,
        label: str,
        value: str = "",
        *,
        status: str | None = None,
        indent: int = 2,
        column: int | None = None,
    ) -> None:
        """A label, after its status if it has one, and its value in the column; a value
        the line cannot hold goes below the label, wrapped."""
        label, value = clean(label), clean(value)
        lead = " " * indent + (self.label(status) if status else "")
        start = indent + (STATUS if status else 0)
        column = column or self.column([label])
        if not value:
            self.write((lead + label).rstrip())
        elif start + column + len(value) <= self.width:
            self.write(lead + label.ljust(column) + value)
        else:
            self.write(lead + label)
            # Below a status row, under its label; below a plain one, further in.
            self.wrapped(value, indent=start if status else indent + 2)

    def wrapped(self, text: str, *, indent: int, style: str | None = None) -> None:
        """Text wrapped at spaces to the terminal; a word longer than a line, such as a
        path, stays whole."""
        width = max(self.width - indent, 24)
        lines = textwrap.wrap(clean(text), width, break_long_words=False, break_on_hyphens=False)
        for line in lines or [""]:
            self.write(" " * indent + (self.paint(line, style) if style else line))

    def item(self, lead: str, text: str, *, indent: int) -> None:
        """An option: its lead, such as ``1  Default bundle``, then its text, wrapped under
        the text's own start."""
        hang = indent + len(lead)
        width = max(self.width - hang, 24)
        lines = textwrap.wrap(clean(text), width, break_long_words=False, break_on_hyphens=False)
        for index, line in enumerate(lines or [""]):
            self.write(" " * indent + (lead if index == 0 else " " * len(lead)) + line)

    def note(self, text: str, *, indent: int) -> None:
        """A detail below an entry, dimmed."""
        self.wrapped(text, indent=indent, style=DIM)

    def verbatim(self, text: str, *, indent: int = 0) -> None:
        """Lines as they are, such as a diagnostic: never wrapped, so each stays whole."""
        for line in clean(text).splitlines():
            auxiliary = line.lstrip().startswith(("at ", "additional"))
            self.write(" " * indent + (self.paint(line, DIM) if auxiliary else line))

    def command(self, text: str) -> None:
        """A command to copy, on a line of its own."""
        self.write("  " + self.paint(clean(text), SIGNAL_CYAN))

    def table(
        self,
        header: Sequence[str] | None,
        rows: Sequence[tuple[str, Sequence[str]]],
        *,
        indent: int = 2,
        fit: bool = True,
        column: int | None = None,
    ) -> bool:
        """A label column, ``column`` wide or as its labels need, and right-aligned value
        columns, under a header if there is one; with ``fit``, False, printing nothing, if
        the terminal is too narrow for it."""
        labels = [*(header[:1] if header else ()), *(label for label, _ in rows)]
        first = column or max(map(len, labels)) + GAP
        columns = len(header) - 1 if header else len(rows[0][1])
        widths = [
            max([len(header[i + 1]) if header else 0, *(len(values[i]) for _, values in rows)])
            for i in range(columns)
        ]
        if fit and indent + first + sum(widths) + GAP * (columns - 1) > self.width:
            return False

        def line(label: str, values: Sequence[str]) -> str:
            cells = (" " * GAP).join(
                value.rjust(width) for value, width in zip(values, widths, strict=True)
            )
            return " " * indent + label.ljust(first) + cells

        if header:
            self.write(line(header[0], header[1:]))
        for label, values in rows:
            self.write(line(label, values))
        return True

    # Setup steps

    def _step(self, number: int, name: str, text: str) -> str:
        return f"{number:02d}  {name.ljust(STEP)}{text}".rstrip()

    def begin(self, number: int, name: str) -> None:
        """The current step, in signal cyan; a terminal keeps it on its line to update."""
        self._settle()
        if self.live:
            self._emit(self.paint(f"{number:02d}  {name}", SIGNAL_CYAN), flush=True)
        self._open = (number, name)

    def progress(self, text: str) -> None:
        """The current step's progress: on its line on a terminal, cut to fit; otherwise a
        line below it."""
        text = clean(text)
        if self._open is None or not self.live:
            self._settle()
            self._emit(" " * 4 + text + "\n", flush=True)
            return
        line = self._step(*self._open, text)
        if len(line) >= self.width:
            line = line[: max(self.width - 2, 1)] + "…"
        self._emit("\r\033[K" + self.paint(line, SIGNAL_CYAN), flush=True)

    def step(self, number: int, name: str, summary: str) -> None:
        """A step done, taking the place of its line in progress."""
        if self._open == (number, name):
            self._emit("\r\033[K" if self.live else "")
            self._open = None
        self._settle()
        self._emit(self._step(number, name, clean(summary)) + "\n", flush=True)

    def prompt(self, question: str) -> str:
        """A question as it is asked: under the current step, in signal cyan. One too long
        for the line is wrapped, indented; its last line is where the answer is typed."""
        self._settle()
        text = clean(question)
        width = max(self.width - 4, 24)
        lines = textwrap.wrap(text, width, break_long_words=False, break_on_hyphens=False)
        lines = lines or [""]
        for line in lines[:-1]:
            self._emit(" " * 4 + self.paint(line, SIGNAL_CYAN) + "\n", flush=True)
        last = lines[-1] + text[len(text.rstrip()) :]  # The space before the answer stays.
        return " " * 4 + self.paint(last, SIGNAL_CYAN)

    def ask(self, question: str) -> str:
        """The answer to a question asked on this report's stream."""
        shown = self.prompt(question)
        if self.stream is sys.stdout:
            return input(shown)
        self._emit(shown, flush=True)  # stdout is left to what the command prints there.
        return input()
