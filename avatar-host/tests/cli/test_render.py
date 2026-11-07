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
import re
from types import SimpleNamespace
from unittest import mock

import pytest

from alphaavatar.host.cli.commands import doctor as doctor_command
from alphaavatar.host.cli.render import Report
from alphaavatar.host.doctor import (
    CHECKS,
    Check,
    CheckStatus,
    Metric,
    Report as Diagnosis,
    ScenarioOutcome,
    ScenarioResult,
)
from alphaavatar.host.log.format import BRAND_BLUE, GREEN, RESET, SIGNAL_CYAN

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
    from alphaavatar.host.doctor.measure import summarize

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
    from alphaavatar.host.configs.capabilities import Missing

    item = Missing(
        "loop.plugin: no installed package provides loop 'realtime'; `alphaavatar setup` "
        "installs it (alpha-avatar-plugins-loop)",
        "loop.plugin",
        "no installed package provides loop 'realtime'",
        "alpha-avatar-plugins-loop",
        "`alphaavatar setup` installs it",
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
        "        `alphaavatar setup` installs it",
    ]
