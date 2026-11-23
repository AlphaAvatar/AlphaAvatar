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
"""The look config init, config check, setup and doctor share in their text reports, and how
setup asks its questions.

A report is a title, a status, then groups of rows: labels in one column, values aligned in
the next. A value too long for the terminal goes below its label, indented and wrapped at
spaces; diagnostics print as they are, so their lines stay whole. Colors decorate text on a
terminal only: pipes, ``NO_COLOR`` and ``TERM=dumb`` get the same structure in plain text,
and JSON never comes here. Callers pass text already redacted; it is control-character
cleaned before it is styled.
"""

from __future__ import annotations

import contextlib
import os
import sys
import textwrap
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from alphaavatar.core.log.records import Redactor, clean
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
VISIBLE = 8  # The options a list shows at once; it scrolls past them.
HINTS = ("↑↓ to move, type to narrow, Enter to choose", "↑↓, type, Enter")  # Beside its question.
# Where a stream cannot encode them, as an ASCII terminal.
_ASCII = str.maketrans({"·": "-", "→": "->", "—": "-", "…": "...", "›": ">", "↑": "^", "↓": "v"})
_ARROWS = {b"\x1b[A": -1, b"\x1bOA": -1, b"\x1b[B": 1, b"\x1bOB": 1}


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


def _key(fd: int) -> bytes:
    """One key from a terminal: a character, or an arrow's whole sequence."""
    import select

    key = os.read(fd, 1)
    # An arrow sends its sequence at once; Escape alone sends nothing after it.
    while key[:1] == b"\x1b" and len(key) < 3 and select.select([fd], [], [], 0.05)[0]:
        key += os.read(fd, 1)
    return key


def home_relative(path: str | Path) -> str:
    """A path for people to read: under the home directory, from ``~``."""
    try:
        return "~/" + str(Path(path).relative_to(Path.home()))
    except ValueError:
        return str(path)


@dataclass(frozen=True, slots=True)
class Option:
    """One answer to a question with options: what is shown, which typing narrows a list to,
    and what choosing it gives."""

    label: str
    value: Any


class Report:
    """One command's text report on its stream: stdout, or stderr for what must leave
    stdout to JSON or to the command's result."""

    def __init__(self, stream: TextIO | None = None, *, width: int | None = None) -> None:
        self.stream = stream if stream is not None else sys.stdout
        self.color = use_color("auto", self.stream)
        # A terminal updates a step's line in place; a pipe or log gets each line.
        tty = bool(getattr(self.stream, "isatty", lambda: False)())
        # NO_COLOR and TERM=dumb ask for plain lines: none erased or redrawn either.
        self.tty = tty
        self.live = tty and os.getenv("TERM") != "dumb" and "NO_COLOR" not in os.environ
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
        self._waiting = False  # A pending line a terminal shows until something follows.
        self.lines = 0  # Lines written so far.

    # Output

    def _emit(self, text: str, *, flush: bool = False) -> None:
        self.stream.write(text.translate(_ASCII) if self._ascii else text)
        self.lines += text.count("\n")
        if flush or self.tty:  # Steps and questions show at once; a pipe buffers the rest.
            self.stream.flush()

    def pending(self, text: str) -> None:
        """What is under way, on a line a terminal erases once something follows."""
        if self.live:
            self._settle()
            self._emit("\r\033[K" + self.paint(clean(text), SIGNAL_CYAN), flush=True)
            self._waiting = True

    def _settle(self) -> None:
        """End a step's line in progress, leaving it shown, before what goes below it; erase
        a pending line."""
        if self._waiting:
            self._emit("\r\033[K")
            self._waiting = False
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

    def missing(self, items: Sequence[Any], *, indent: int) -> None:
        """Each setting at fault on its line, whole where the terminal holds it; else its
        parts on lines of their own: the setting, what is wrong, the package, what fixes it."""
        redact = Redactor()
        for item in items:
            line = redact(clean(item.line), limit=None)
            if indent + len(line) <= self.width:
                self.write(" " * indent + line)
                continue
            self.write(" " * indent + redact(clean(item.location), limit=None))
            for part in (item.problem, item.package, item.action):
                if part:
                    self.wrapped(redact(part, limit=None), indent=indent + 2)

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
            return (" " * indent + label.ljust(first) + cells).rstrip()

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
            width = max(self.width - 4, 24)
            lines = textwrap.wrap(text, width, break_long_words=False, break_on_hyphens=False)
            for line in lines or [""]:
                self._emit(" " * 4 + line + "\n", flush=True)
            return
        line = self._step(*self._open, text)
        if len(line) >= self.width:
            line = line[: max(self.width - 2, 1)] + "…"
        self._emit("\r\033[K" + self.paint(line, SIGNAL_CYAN), flush=True)

    def step(self, number: int, name: str, summary: str) -> None:
        """A step done, taking the place of its line in progress. A summary the line cannot
        hold goes on at its own column, a ``·`` part at a time."""
        if self._open == (number, name):
            self._emit("\r\033[K" if self.live else "")
            self._open = None
        self._settle()
        hang, lines = 4 + STEP, [""]
        for part in clean(summary).split(" · "):
            joined = f"{lines[-1]} · {part}" if lines[-1] else part
            if lines[-1] and hang + len(joined) > self.width:
                lines.append(part)
            else:
                lines[-1] = joined
        self._emit(self._step(number, name, lines[0]) + "\n", flush=True)
        for line in lines[1:]:
            self._emit(" " * hang + line + "\n", flush=True)

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
        """The answer to a question asked on this report's stream. Left with Ctrl+C or at
        the input's end, the question's line is ended: what follows starts on its own."""
        shown = self.prompt(question)
        try:
            if self.stream is sys.stdout:
                return input(shown)
            self._emit(shown, flush=True)  # stdout is left to what the command prints there.
            return input()
        except (KeyboardInterrupt, EOFError):
            self._emit("\n", flush=True)
            raise

    def _numbered(self, question: str, options: Sequence[Option], default: int) -> Any:
        """The options numbered, then the question: a number takes its option, as does text
        only one option's label holds; Enter, the default."""
        for index, option in enumerate(options, 1):
            mark = "  (default)" if index - 1 == default else ""
            self.item(f"{index:<3}", option.label + mark, indent=6)
        while True:
            answer = self.ask(f"{question} [{default + 1}]: ").strip()
            if not answer:
                return options[default].value
            if answer.isdigit() and 1 <= int(answer) <= len(options):
                return options[int(answer) - 1].value
            held = [option for option in options if answer.casefold() in option.label.casefold()]
            if len(held) == 1:
                return held[0].value
            self.wrapped(f"A number from 1 to {len(options)}, or text one option holds", indent=6)

    def _fit(self, text: str, used: int) -> str:
        """Text cut to the terminal's width after ``used`` columns: a list redraws only lines it
        can count, none wrapped. The cut's mark is three columns where a stream is ASCII."""
        room = max(self.width - used - 1, 8)
        return text if len(text) <= room else text[: room - 3] + "…"

    def _show_cursor(self) -> None:
        # Unwritable, it stays as it is: what ended the list is what is reported.
        with contextlib.suppress(OSError, ValueError):
            self._emit("\033[?25h", flush=True)

    def _listed(self, question: str, options: Sequence[Option], default: int) -> Any:
        """The options under the question, one marked: the arrows move the mark, typing
        narrows the list to the labels holding what is typed, Escape clears it, Enter takes
        the one marked. The terminal is as it was however this ends."""
        import termios
        import tty

        fd = sys.stdin.fileno()
        saved = termios.tcgetattr(fd)
        typed, marked, shown = "", default, 0

        head = self._fit(f"{question}:", 4)
        asked = self.paint(head, SIGNAL_CYAN)
        room = self.width - 1 - 4 - len(head) - 1  # What the hint, or what is typed, may take.

        def erase() -> None:
            # Back to the question's line, and everything below it cleared.
            self._emit((f"\033[{shown}A" if shown else "") + "\r\033[J", flush=True)

        try:
            tty.setcbreak(fd)  # Each key as typed, none echoed; Ctrl+C still interrupts.
            self._settle()
            self._emit("\033[?25l")  # No cursor blinking through the list as it redraws.
            while True:
                # The options holding what is typed, the mark on one, the window around it.
                held = [
                    index
                    for index, option in enumerate(options)
                    if typed.casefold() in option.label.casefold()
                ]
                if held and marked not in held:
                    marked = held[0]
                at = held.index(marked) if held else 0
                start = max(0, min(at - VISIBLE + 1, len(held) - VISIBLE))

                if typed:  # Its end, where it is typed.
                    hint = self.paint(typed[-max(room, 0) :] if room > 0 else "", SIGNAL_CYAN)
                else:  # How to choose, shorter where the line is narrow, else not at all.
                    fits = [hint for hint in HINTS if len(hint) <= room]
                    hint = self.paint(fits[0] if fits else "", DIM)
                lines = [f"    {asked} {hint}".rstrip()]
                for index in held[start : start + VISIBLE]:
                    mark = "  (default)" if index == default else ""
                    label = self._fit(clean(options[index].label), 6 + len(mark))
                    label += self.paint(mark, DIM)
                    lines.append(
                        "    " + self.paint(f"› {label}", SIGNAL_CYAN)
                        if index == marked
                        else f"      {label}"
                    )
                if not held:
                    lines.append("      " + self.paint("No option holds that", DIM))
                erase()
                self._emit("\n".join(lines) + "\n", flush=True)
                shown = len(lines)

                key = _key(fd)
                if key in (b"", b"\x04"):  # The input's end, or Ctrl+D.
                    raise EOFError
                if key in _ARROWS and held:
                    marked = held[(at + _ARROWS[key]) % len(held)]
                elif key in (b"\r", b"\n") and held:
                    break
                elif key in (b"\x7f", b"\x08"):
                    typed = typed[:-1]
                elif key == b"\x1b":
                    typed = ""
                elif len(key) == 1 and 32 <= key[0] < 127:
                    typed += key.decode()

            erase()
            self._emit(f"    {asked} {clean(options[marked].label)}\n", flush=True)
            return options[marked].value
        except BaseException:
            # Ended here: the question stays, its line ended, for what follows.
            erase()
            self._emit(f"    {asked}\n", flush=True)
            raise
        finally:
            # The terminal's settings as they were, before anything else. A signal's handler
            # raises between any two steps here: its exception waits while they are restored
            # again, and while the cursor is shown, then goes on.
            stop: BaseException | None = None
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, saved)
            except (KeyboardInterrupt, SystemExit) as error:
                stop = error
                termios.tcsetattr(fd, termios.TCSADRAIN, saved)

            try:
                self._show_cursor()
            except (KeyboardInterrupt, SystemExit) as error:
                stop = stop or error
                self._show_cursor()

            if stop is not None:
                raise stop

    def choose(self, question: str, options: Sequence[Option], default: int = 0) -> Any:
        """The value of the option chosen: from a list on a terminal that redraws, the
        report's and the input's both; otherwise by number, as with ``TERM=dumb``,
        ``NO_COLOR`` or no terminal. Ctrl+C and the input's end leave as ``ask`` does."""
        if not options:
            raise ValueError("A question with options needs one")
        try:
            import termios  # noqa: F401
        except ImportError:  # No terminal control here: numbered.
            return self._numbered(question, options, default)
        if self.live and sys.stdin.isatty():
            return self._listed(question, options, default)
        return self._numbered(question, options, default)
