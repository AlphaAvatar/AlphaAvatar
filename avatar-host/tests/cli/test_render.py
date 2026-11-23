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
"""The shared text reports: aligned on a wide terminal, wrapped on a narrow one, styled only
on a terminal, and Doctor's figures as measured, a dash for what was not."""

from __future__ import annotations

import io
import os
import pty
import re
import select
import signal
import subprocess
import sys
import termios
import time
from types import SimpleNamespace
from unittest import mock

import pytest

from alphaavatar.host.cli.commands import doctor as doctor_command
from alphaavatar.host.cli.render import Option, Report
from alphaavatar.host.log.format import BRAND_BLUE, GREEN, RESET, SIGNAL_CYAN
from alphaavatar.host.tools.doctor import (
    CHECKS,
    Check,
    CheckStatus,
    Metric,
    Report as Diagnosis,
    ScenarioOutcome,
    ScenarioResult,
)

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
COLOR = re.compile(r"\x1b\[[0-9;]*m")  # Styles alone; line erases stay.
REASON = (
    "Not run: the session would reach external services, and host.doctor.external_services is false"
)


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture
def color_capable() -> object:
    """Styling assertions must not depend on an inherited NO_COLOR or TERM=dumb."""
    with mock.patch.dict(os.environ, {"TERM": "xterm-256color"}):
        os.environ.pop("NO_COLOR", None)
        os.environ.pop("COLUMNS", None)
        yield


def sample(out: Report) -> None:
    out.title("Sample")
    out.status("OK", "Bundle created")
    out.heading("Configuration")
    column = out.column(["Profiles", "Default"])
    out.row(
        "Profiles", "/home/me/.local/share/alphaavatar/configs/profiles/my-avatar", column=column
    )
    out.row("Default", "my-avatar", column=column)
    out.row("router", "default  (audio activity on, semantic addressing on, visual addressing on)")
    out.heading("Not verified")
    out.row("Session and services", status="SKIP")
    out.wrapped(REASON, indent=8)
    out.heading("Next")
    out.command("alphaavatar doctor my-avatar")


def test_a_wide_terminal_aligns_values_and_a_narrow_one_wraps_them_below(
    color_capable: object,
) -> None:
    wide, narrow = io.StringIO(), io.StringIO()
    sample(Report(wide, width=100))
    sample(Report(narrow, width=72))
    assert wide.getvalue().splitlines()[1:] == [
        "AlphaAvatar / Sample",
        "OK    Bundle created",
        "",
        "Configuration",
        "  Profiles     /home/me/.local/share/alphaavatar/configs/profiles/my-avatar",
        "  Default      my-avatar",
        "  router       default  (audio activity on, semantic addressing on, visual addressing on)",
        "",
        "Not verified",
        "  SKIP  Session and services",
        "        Not run: the session would reach external services, and host.doctor.external_services is",
        "        false",
        "",
        "Next",
        "  alphaavatar doctor my-avatar",
    ]
    lines = narrow.getvalue().splitlines()
    # Too long for 72 columns: the value goes below its label, wrapped at spaces; a path,
    # one word, whole.
    assert lines[5:16] == [
        "  Profiles",
        "    /home/me/.local/share/alphaavatar/configs/profiles/my-avatar",
        "  Default      my-avatar",
        "  router",
        "    default  (audio activity on, semantic addressing on, visual",
        "    addressing on)",
        "",
        "Not verified",
        "  SKIP  Session and services",
        "        Not run: the session would reach external services, and",
        "        host.doctor.external_services is false",
    ]
    assert all(len(line) <= 72 for line in lines)
    # A word longer than a line stays whole: a path is never cut.
    out = io.StringIO()
    Report(out, width=40).row("Profiles", "/home/me/.local/share/alphaavatar/configs/x")
    assert out.getvalue().splitlines() == [
        "  Profiles",
        "    /home/me/.local/share/alphaavatar/configs/x",
    ]


@pytest.mark.parametrize(
    "environment",
    [{}, {"NO_COLOR": ""}, {"TERM": "dumb"}],
    ids=["terminal", "no-color", "dumb-terminal"],
)
def test_styles_are_a_terminals_alone_and_the_structure_is_the_same_without(
    environment: dict[str, str], color_capable: object
) -> None:
    pipe, terminal = io.StringIO(), Terminal()
    with mock.patch.dict(os.environ, environment):
        sample(Report(pipe, width=72))
        sample(Report(terminal, width=72))
    styled = not environment
    shown = terminal.getvalue()
    assert ("\x1b" in shown) == styled and "\x1b" not in pipe.getvalue()
    assert ANSI.sub("", shown) == pipe.getvalue()  # The same lines, only undecorated.
    if styled:
        lines = shown.splitlines()
        assert lines[1] == f"{BRAND_BLUE}AlphaAvatar / Sample{RESET}"
        assert lines[2] == f"{GREEN}OK{RESET}    Bundle created"
        assert f"  {SIGNAL_CYAN}alphaavatar doctor my-avatar{RESET}" in lines
        # Values, paths and labels keep the default foreground.
        assert "  Default      my-avatar" in lines


def test_a_step_in_progress_takes_one_terminal_line_and_a_pipe_gets_what_goes_below(
    color_capable: object,
) -> None:
    def steps(out: Report) -> None:
        out.begin(3, "Install")
        out.progress("[1/2] a.whl")
        out.progress("[2/2] b.whl")
        out.step(3, "Install", "2 packages · 1 MB")
        out.begin(4, "Validate")
        out.step(4, "Validate", "PASS · 8 runners")

    terminal, pipe, plain = Terminal(), io.StringIO(), Terminal()
    steps(Report(terminal, width=72))
    steps(Report(pipe, width=72))
    with mock.patch.dict(os.environ, {"NO_COLOR": ""}):
        steps(Report(plain, width=72))
    # On a terminal each update replaces the step's line, and the result replaces them.
    assert COLOR.sub("", terminal.getvalue()) == (
        "03  Install"
        "\r\x1b[K03  Install        [1/2] a.whl"
        "\r\x1b[K03  Install        [2/2] b.whl"
        "\r\x1b[K03  Install        2 packages · 1 MB\n"
        "04  Validate"
        "\r\x1b[K04  Validate       PASS · 8 runners\n"
    )
    # NO_COLOR, on a terminal too: no line erased or redrawn, each line once, as a pipe has it.
    assert plain.getvalue() == pipe.getvalue() and "\x1b" not in plain.getvalue()
    # A pipe or log: each line once, a step's name before what goes under it.
    assert pipe.getvalue().splitlines() == [
        "03  Install",
        "    [1/2] a.whl",
        "    [2/2] b.whl",
        "03  Install        2 packages · 1 MB",
        "04  Validate       PASS · 8 runners",
    ]
    # A long progress line is cut to the terminal, so updating it never wraps.
    out = Terminal()
    report = Report(out, width=40)
    report.begin(3, "Install")
    report.progress("[1/2] " + "a" * 60 + ".whl")
    assert max(map(len, COLOR.sub("", out.getvalue()).split("\r\x1b[K"))) <= 40
    # Nothing to update in a pipe or with NO_COLOR: a long progress line wraps instead, a
    # path whole; and a step's summary goes on at its own column, a part at a time.
    pipe = io.StringIO()
    report = Report(pipe, width=72)
    report.begin(3, "Install")
    envs = "/home/tester/.local/lib/alphaavatar/envs/5787e9bba63c388c"
    report.progress(f"Environment {envs} is already installed; checking it")
    report.step(1, "Capabilities", "Bundle reference · Voice on · Vision on · Local models on")
    assert pipe.getvalue().splitlines() == [
        "03  Install",
        "    Environment",
        f"    {envs} is already",
        "    installed; checking it",
        "01  Capabilities   Bundle reference · Voice on · Vision on",
        "                   Local models on",
    ]


def test_a_stream_that_cannot_encode_the_separators_gets_ascii(color_capable: object) -> None:
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="ascii")
    out = Report(stream, width=100)
    out.status("OK", "Bundle reference · Voice on")
    out.row("Speech end → STT final", "—")
    stream.flush()
    assert raw.getvalue().decode().splitlines() == [
        "OK    Bundle reference - Voice on",
        "  Speech end -> STT final   -",
    ]


def metric(name: str, value: float | None, note: str | None = None, **fields) -> Metric:
    return Metric(name, value, "ms", "start", "end", "boundary", note=note, **fields)


def diagnosis(*scenarios: ScenarioResult) -> Diagnosis:
    """Every check passed but the media devices; the session ran these rounds."""
    from alphaavatar.host.tools.doctor.measure import summarize

    checks = []
    for spec in CHECKS:
        status = CheckStatus.SKIP if spec.id == "devices.media" else CheckStatus.PASS
        found = scenarios if spec.id == "session.scenarios" else ()
        summaries = summarize(list(scenarios)) if found else ()
        checks.append(
            Check(spec.id, status, f"{spec.id} summary", scenarios=found, summaries=summaries)
        )
    return Diagnosis(tuple(checks))


def voice(at: int, first_text: float, **fields) -> ScenarioResult:
    """A round of the two-sentence question; the third's VAD close came out of order."""
    merged = at == 3
    return ScenarioResult(
        "voice",
        fields.pop("outcome", ScenarioOutcome.PASSED),
        "Answered as the task expects",
        "stt openai_segment m · vision off",
        metrics=(
            metric("first_text", first_text),
            metric("first_audio_frame", first_text + 400),
            metric("response_final", first_text + 1100),
        ),
        segments=(
            metric("input", 640.0 + at),
            metric("input.vad_close", None if merged else 600.0 + at, merged=()),
            metric(
                "input.final_transcript",
                40.0 if not merged else 643.0,
                merged=("vad_close",) * merged,
            ),
            metric("output", 330.0),
            metric("output.first_pcm", None, "merged into the next row: First PCM not observed"),
            metric("output.first_audio_frame", 21.0, merged=("first_pcm",)),
        ),
        round=at,
        sample="sum_question sha256:0123456789ab",
        **fields,
    )


ROUNDS = (
    # Stopped before any audio: what it measured stays, apart from the passed rounds.
    voice(
        1,
        712.4,
        outcome=ScenarioOutcome.FAILED,
        blocked_stage="audio.first",
        cause="TTS refused the request",
    ),
    voice(2, 640.0),
    voice(3, 690.0),
)


def text(width: int, *, interrupted: bool = False, overridden: bool = False) -> list[str]:
    out = io.StringIO()
    report = Report(out, width=width)
    prepared = SimpleNamespace(loaded=None, rounds=3)
    doctor_command._text(report, diagnosis(*ROUNDS), prepared, "alpha", overridden, interrupted)
    return out.getvalue().splitlines()


def test_doctor_summarizes_each_scenarios_rounds_the_first_apart_the_failed_apart() -> None:
    wide = text(100)
    assert wide[0] == "OK    Diagnostics completed · 14 passed · 1 skipped"
    # The scenario's rounds on one line; a failed round's reason below, once per reason; what
    # the rounds ran with, and the sample they heard.
    start = wide.index("Scenarios · 3 rounds, a session each")
    assert wide[start + 1 : start + 5] == [
        "  FAIL  voice                  2/3 passed · stopped: 1 at audio.first",
        "        Round 1: cause: TTS refused the request",
        "  With stt openai_segment m · vision off",
        "  Sample sum_question sha256:0123456789ab",
    ]
    # Each figure over the passed rounds: the first round, failed, is no sample of them; each
    # stage's total on its line, its rows under it; a merged value is no sample of its row.
    start = wide.index("Latency · voice · 2 of 3 rounds passed")
    assert wide[start + 1 : start + 13] == [
        "  Metric                            Round 1   n     Median            Range",
        "  End to end",
        "    Runtime first text                    —   2     665 ms       640–690 ms",
        "    First audio frame                     —   2   1,065 ms   1,040–1,090 ms",
        "    Response complete                     —   2   1,765 ms   1,740–1,790 ms",
        "  Input                                   —   2     642 ms       642–643 ms",
        "    Final speech → VAD close              —   1     602 ms           602 ms",
        "    VAD close → Final transcript          —   1      40 ms            40 ms",
        "  Output                                  —   2     330 ms           330 ms",
        "    TTS request → First PCM               —   0          —                —",
        "    First PCM → First audio frame         —   0          —                —",
        "  n: later rounds that passed and observed it; the stages add up to First audio frame",
    ]
    merged = "  — VAD close → Final transcript: from an earlier node in 1 round, so no sample of it"
    assert merged in wide
    assert "  — TTS request → First PCM: merged into the next row: First PCM not observed" in wide
    # Every round, the failed one included: its figures counted apart, its Round 1 shown.
    start = wide.index("Latency · voice · every round, the 1 not passed included")
    assert wide[start + 3] == (
        "    Runtime first text                712 ms   2     665 ms       640–690 ms"
    )
    assert wide[start + 6] == (
        "  Input                               641 ms   2     642 ms       642–643 ms"
    )
    assert wide[start + 12] == (
        "  n: later rounds that observed it; the stages add up to First audio frame"
    )
    start = wide.index("Failed rounds · voice")
    assert wide[start + 1 : start + 3] == [
        "  Round 1 · stopped at audio.first · measured: Runtime first text 712 ms; First audio "
        "frame 1,112",
        "  ms; Response complete 1,812 ms; Input 641 ms; Output 330 ms",
    ]
    assert all(line == line.rstrip() for line in wide)
    # The diagnosis run again as JSON, as many rounds; overrides never repeated, only said to
    # be needed.
    assert wide[-3:] == ["Run again as JSON", "  alphaavatar doctor alpha --rounds 3 --json", ""]
    assert text(100, overridden=True)[-2] == (
        "  With the same KEY=VALUE overrides, which are not repeated here."
    )
    # Too narrow for the table: each figure on its own lines, in the same words.
    narrow = text(60)
    start = narrow.index("Latency · voice · 2 of 3 rounds passed")
    assert narrow[start + 1 : start + 3] == [
        "  End to end",
        "    Runtime first text: round 1 — · 2 later: median 665 ms,",
    ]
    assert "  Input: round 1 — · 2 later: median 642 ms, 642–643 ms" in narrow
    assert text(100, interrupted=True)[0] == "WARN  Interrupted · 14 passed · 1 skipped"


def test_a_question_too_long_for_the_line_is_wrapped_and_answered_on_its_last(
    color_capable: object,
) -> None:
    out = io.StringIO()
    question = "OPENAI_API_KEY, for the model, embeddings and speech (set; Enter keeps it): "
    asked = Report(out, width=48).prompt(question)
    assert out.getvalue() == "    OPENAI_API_KEY, for the model, embeddings\n"
    assert asked == "    and speech (set; Enter keeps it): "  # Typed after its space.
    assert Report(io.StringIO(), width=100).prompt(question) == f"    {question}"


def test_the_width_is_columns_else_the_streams_own_terminal_else_100(color_capable: object) -> None:
    class Sized(Terminal):
        def fileno(self) -> int:
            return 99

    def size(fd: int) -> os.terminal_size:
        if fd != 99:
            raise OSError("not a terminal")
        return os.terminal_size((88, 24))

    with mock.patch("os.get_terminal_size", size):
        # A pipe or a file has no width of its own, whatever started the process.
        assert Report(io.StringIO()).width == 100
        assert Report(Sized()).width == 88
        with mock.patch.dict(os.environ, {"COLUMNS": "72"}):
            assert Report(Sized()).width == Report(io.StringIO()).width == 72


def test_a_missing_package_too_long_for_the_line_shows_its_parts_apart(
    color_capable: object,
) -> None:
    from alphaavatar.host.configs import Problem

    item = Problem(
        "loop.plugin: no installed package provides loop 'realtime'; `alphaavatar setup alpha` "
        "installs it (alpha-avatar-plugins-loop)",
        "loop.plugin",
        "no installed package provides loop 'realtime'",
        "alpha-avatar-plugins-loop",
        "`alphaavatar setup alpha` installs it",
    )
    wide, narrow = io.StringIO(), io.StringIO()
    Report(wide, width=200).missing([item], indent=6)
    Report(narrow, width=72).missing([item], indent=6)
    assert wide.getvalue() == f"      {item.line}\n"  # Whole where it fits, as searched for.
    # Narrow: the setting, then what is wrong, the package and what installs it, a line each.
    assert narrow.getvalue().splitlines() == [
        "      loop.plugin",
        "        no installed package provides loop 'realtime'",
        "        alpha-avatar-plugins-loop",
        "        `alphaavatar setup alpha` installs it",
    ]


PROVIDERS = [Option(name, name.lower()) for name in ("OpenAI", "Anthropic", "Google", "OpenRouter")]


def test_options_without_a_terminal_are_numbered_and_answered_by_number_or_text(
    color_capable: object,
) -> None:
    out = io.StringIO()
    # Out of range, then text two labels hold, then text only one holds.
    queue = ["9", "open", "rout", "", "3"]
    with mock.patch("builtins.input", lambda prompt="": queue.pop(0)):
        assert Report(out, width=100).choose("Provider for memory", PROVIDERS, 1) == "openrouter"
        assert Report(out, width=100).choose("Provider for memory", PROVIDERS, 1) == "anthropic"
        assert Report(out, width=100).choose("Provider for memory", PROVIDERS, 1) == "google"
    assert queue == []
    shown = out.getvalue().splitlines()
    assert shown[:4] == [
        "      1  OpenAI",
        "      2  Anthropic  (default)",
        "      3  Google",
        "      4  OpenRouter",
    ]
    # (Answered here without a terminal's echo, so a prompt and the next line share one.)
    assert out.getvalue().count("      A number from 1 to 4, or text one option holds\n") == 2
    assert "\033" not in out.getvalue()  # Plain: no list is drawn where nothing redraws.


CHOOSER = """
import fcntl, os, sys, termios
from alphaavatar.host.cli.render import Option, Report
os.setsid()  # The terminal this reads becomes its own: Ctrl+C reaches it as a person's would.
fcntl.ioctl(0, termios.TIOCSCTTY, 0)
options = [Option(name, name.lower()) for name in ("OpenAI", "Anthropic", "Google", "OpenRouter")]
try:
    chosen = Report(sys.stdout).choose("Provider for memory", options, 1)
except KeyboardInterrupt:
    chosen = "interrupted"
except EOFError:
    chosen = "ended"
print("chosen:", chosen, flush=True)
"""


def listed(*keys: bytes, columns: int = 100) -> tuple[str, str, bool, bool]:
    """``choose`` on a real terminal, each key typed once the list is drawn again: what it
    gave, the screen's last state as text, whether the terminal read keys unechoed and one by
    one while the list was up, and whether its settings were as before once it ended."""
    import fcntl
    import pty
    import select
    import struct
    import subprocess
    import termios
    import time

    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, columns, 0, 0))
    before = termios.tcgetattr(slave)
    env = {k: v for k, v in os.environ.items() if k not in ("NO_COLOR", "COLUMNS")}
    child = subprocess.Popen(
        [sys.executable, "-c", CHOOSER],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=env | {"TERM": "xterm-256color"},
        start_new_session=False,
        pass_fds=(),
    )
    received, cbreak = b"", True

    def read_until(marker: bytes, seen: int) -> int:
        nonlocal received
        end = time.monotonic() + 30
        while (at := received.find(marker, seen)) < 0:
            assert time.monotonic() < end, received.decode(errors="replace")
            if select.select([master], [], [], 0.1)[0]:
                received += os.read(master, 65536)
        return at + len(marker)

    try:
        seen = read_until(b"\033[?25l", 0)  # The list is up.
        for key in keys:
            seen = read_until(b"Provider for mem", seen)  # Cut short on a narrow terminal.
            mode = termios.tcgetattr(slave)[3]
            cbreak &= not mode & (termios.ICANON | termios.ECHO) and bool(mode & termios.ISIG)
            os.write(master, key)
        read_until(b"chosen: ", seen)
        assert child.wait(30) == 0
        while select.select([master], [], [], 0.2)[0]:
            received += os.read(master, 65536)
        restored = termios.tcgetattr(slave) == before
    finally:
        child.kill()
        child.wait()
        os.close(master)
        os.close(slave)
    text = received.decode()
    chosen = text.rsplit("chosen: ", 1)[1].split()[0]
    # The cursor shown again once the list is gone, whatever ended it.
    assert text.rfind("\033[?25h") > text.rfind("\033[?25l")
    return chosen, text, cbreak, restored


@pytest.mark.parametrize(
    ("keys", "chosen", "answered"),
    [
        ((b"\r",), "anthropic", "Anthropic"),  # The default, as marked first.
        ((b"\033[B", b"\033[B", b"\033[B", b"\r"), "openai", "OpenAI"),  # Down past the last.
        ((b"\033[A", b"\n"), "openai", "OpenAI"),
        ((b"g", b"l", b"\r"), "google", "Google"),  # Narrowed to the one holding it.
        # Widened again, the mark stays on what it marked.
        ((b"o", b"p", b"e", b"n", b"r", b"\x7f", b"\x7f", b"\r"), "openrouter", "OpenRouter"),
        ((b"x", b"y", b"\r", b"\033", b"\r"), "anthropic", None),  # Nothing holds xy; cleared.
        ((b"\x03",), "interrupted", None),  # Ctrl+C still interrupts.
        ((b"\x04",), "ended", None),  # Ctrl+D ends the input.
    ],
    ids=["enter", "down-wraps", "up", "typed", "backspace", "nothing-held", "ctrl-c", "ctrl-d"],
)
def test_options_on_a_terminal_are_a_list_the_arrows_and_typing_choose_from(
    keys: tuple[bytes, ...], chosen: str, answered: str | None
) -> None:
    found, text, cbreak, restored = listed(*keys)
    assert (found, cbreak, restored) == (chosen, True, True)
    last = text.rsplit("\033[J", 1)[1]  # What stays once the list is erased.
    plain = re.sub(r"\033\[[0-9;?]*[A-Za-z]", "", last)
    question = "    Provider for memory:"
    assert plain.startswith(f"{question} {answered}\r\n" if answered else question)
    if keys == (b"x", b"y", b"\r", b"\033", b"\r"):
        assert "No option holds that" in text  # And Enter took nothing then.


def test_a_list_too_narrow_for_its_hint_shows_a_shorter_one() -> None:
    found, text, _, restored = listed(b"\r", columns=50)
    assert (found, restored) == ("anthropic", True)
    assert "↑↓, type, Enter" in text and "type to narrow" not in text


def test_a_list_on_a_narrow_terminal_keeps_each_line_it_redraws_within_it() -> None:
    found, text, cbreak, restored = listed(b"\033[B", b"o", b"\r", columns=24)
    assert (found, cbreak, restored) == ("google", True, True)
    # Each line drawn before the answer fits: one that wrapped would be redrawn a line off.
    drawn = re.sub(r"\033\[[0-9;?]*[A-Za-z]", "", text.rsplit("\033[J", 1)[0])
    widths = [len(line.rsplit("\r", 1)[-1]) for line in drawn.split("\n")]
    assert max(widths) <= 23
    assert "    Provider for mem…" in drawn and "    › Anthr…  (default)" in drawn


ENDING = """
import errno, fcntl, os, signal, sys, termios
from alphaavatar.host.cli.commands.setup import _interrupt
from alphaavatar.host.cli.render import Option, Report
os.setsid()
fcntl.ioctl(0, termios.TIOCSCTTY, 0)
signal.signal(signal.SIGTERM, _interrupt)  # As setup has them: each unwinds as SystemExit.
signal.signal(signal.SIGHUP, _interrupt)
point, signum = sys.argv[1], int(sys.argv[2])
fired = []

def fire():
    if not fired:  # Once: the first signal of the list's ending.
        fired.append(signum)
        os.kill(os.getpid(), signum)

import tty  # noqa: E402,F401  Bound to termios as it is: its cbreak call is not the list's ending.

restore = termios.tcsetattr  # The list's own calls from here on.

def tcsetattr(fd, when, attributes):
    if point == "before-restore":
        fire()
    restore(fd, when, attributes)
    if point == "after-restore":
        fire()

emit = Report._emit

def _emit(self, text, *, flush=False):
    if text != "\\033[?25h":
        return emit(self, text, flush=flush)
    if point == "before-cursor":
        fire()
    if point == "cursor-fails":
        raise OSError(errno.EIO, "the terminal took no more")
    emit(self, text, flush=flush)
    if point == "after-cursor":
        fire()

termios.tcsetattr, Report._emit = tcsetattr, _emit
options = [Option(name, name.lower()) for name in ("OpenAI", "Anthropic")]
try:
    Report(sys.stdout).choose("Provider for memory", options, 1)
except KeyboardInterrupt:
    os._exit(130)
except SystemExit as stop:
    os._exit(stop.code)
os._exit(0)
"""


@pytest.mark.parametrize(
    "signum", [signal.SIGTERM, signal.SIGHUP, signal.SIGINT], ids=["TERM", "HUP", "INT"]
)
@pytest.mark.parametrize(
    "point", ["before-restore", "after-restore", "before-cursor", "after-cursor"]
)
def test_a_signal_as_a_list_ends_never_leaves_the_terminal_unrestored(
    point: str, signum: int
) -> None:
    code, restored, mode = ended(point, signum)
    # Ended by the signal, as it would end anywhere; the terminal as before, read first.
    assert code == (130 if signum == signal.SIGINT else 128 + signum)
    assert restored and mode & termios.ICANON and mode & termios.ECHO


def test_a_cursor_the_terminal_takes_no_more_of_leaves_its_settings_restored() -> None:
    code, restored, mode = ended("cursor-fails", 0)
    assert (code, restored) == (0, True)  # Chosen, as Enter chose it.


def ended(point: str, signum: int) -> tuple[int, bool, int]:
    """A list ended with Enter on a real terminal, ``signum`` arriving at ``point`` of its
    ending: the exit status, and the terminal as the list left it, read once it exited while
    this end keeps the terminal open, so neither a hangup nor a shell restores it first."""
    master, slave = pty.openpty()
    before = termios.tcgetattr(slave)
    env = {k: v for k, v in os.environ.items() if k not in ("NO_COLOR", "COLUMNS")}
    child = subprocess.Popen(
        [sys.executable, "-c", ENDING, point, str(signum)],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=env | {"TERM": "xterm-256color"},
    )
    received = b""
    try:
        end = time.monotonic() + 30
        while b"\033[?25l" not in received:  # The list is up.
            assert time.monotonic() < end, received.decode(errors="replace")
            if select.select([master], [], [], 0.1)[0]:
                received += os.read(master, 65536)
        while b"Provider for memory:" not in received.rsplit(b"\033[?25l", 1)[1]:
            assert time.monotonic() < end, received.decode(errors="replace")
            if select.select([master], [], [], 0.1)[0]:
                received += os.read(master, 65536)
        os.write(master, b"\r")
        code = child.wait(30)
        after = termios.tcgetattr(slave)
        while select.select([master], [], [], 0.1)[0]:
            received += os.read(master, 65536)
    finally:
        child.kill()
        child.wait()
        os.close(master)
        os.close(slave)
    return code, after == before, after[3]
