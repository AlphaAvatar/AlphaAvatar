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


def metric(name: str, value: float | None, note: str | None = None) -> Metric:
    return Metric(name, value, "ms", "start", "end", "boundary", note=note)


def diagnosis(*scenarios: ScenarioResult) -> Diagnosis:
    """Every check passed but the media devices; the session ran these scenarios."""
    checks = []
    for spec in CHECKS:
        status = CheckStatus.SKIP if spec.id == "devices.media" else CheckStatus.PASS
        found = scenarios if spec.id == "session.scenarios" else ()
        checks.append(Check(spec.id, status, f"{spec.id} summary", scenarios=found))
    return Diagnosis(tuple(checks))


VISION = ScenarioResult(
    "voice_vision",
    ScenarioOutcome.PASSED,
    "Answered as the task expects",
    "original",
    metrics=(
        metric("first_text", 712.4),
        metric("first_audio_frame", 1108.0),
        metric("response_final", 1840.2),
    ),
    segments=(
        metric("vad_close", 210.0),
        metric("tts_request_to_first_pcm", None, "this TTS plugin logs no first PCM"),
        metric("selected_frame_age", 92.0),
    ),
)
# Stopped before any audio: what was measured stays, the rest is a dash.
TEXT = ScenarioResult(
    "text",
    ScenarioOutcome.FAILED,
    "Stopped at output.audio_frame",
    "original",
    blocked_stage="output.audio_frame",
    cause="TTS refused the request",
    metrics=(metric("first_text", 6.5), metric("first_audio_frame", None)),
)


def text(width: int, *, interrupted: bool = False, overridden: bool = False) -> list[str]:
    out = io.StringIO()
    report = Report(out, width=width)
    prepared = SimpleNamespace(loaded=None)
    doctor_command._text(
        report, diagnosis(VISION, TEXT), prepared, "alpha", overridden, interrupted
    )
    return out.getvalue().splitlines()


def test_doctor_shows_figures_side_by_side_or_one_scenario_after_another() -> None:
    wide = text(100)
    assert wide[0] == "OK    Diagnostics completed · 14 passed · 1 skipped"
    start = wide.index("End-to-end latency")
    assert wide[start + 1 : start + 7] == [
        "  Metric              voice_vision     text",
        "  First text                712 ms   6.5 ms",
        "  First audio frame       1,108 ms        —",
        "  Response complete       1,840 ms        —",
        # A dash says why: where the scenario stopped.
        "  — First audio frame · text: not reached: stopped at output.audio_frame",
        "  — Response complete · text: not reached: stopped at output.audio_frame",
    ]
    # Each scenario's stages, as measured: a stage observed nowhere is a dash, never 0 ms, and
    # its note says why.
    start = wide.index("Stage timing · voice_vision")
    assert wide[start + 1 : start + 5] == [
        "  Speech end → VAD close                210 ms",
        "  TTS request → First PCM                    —",
        "  Selected frame age at model request    92 ms",
        "  — TTS request → First PCM: this TTS plugin logs no first PCM",
    ]
    assert "Stage timing · text" not in wide  # It measured no stage.
    # The failed scenario: where it stopped and why.
    assert "  FAIL  text                   Stopped at output.audio_frame" in wide
    assert "        cause: TTS refused the request" in wide
    assert "  PASS  voice_vision           Speech and screen frames in one model request" in wide
    # The diagnosis run again as JSON; overrides never repeated, only said to be needed.
    assert wide[-3:] == ["Run again as JSON", "  alphaavatar doctor alpha --json", ""]
    assert text(100, overridden=True)[-2] == (
        "  With the same KEY=VALUE overrides, which are not repeated here."
    )

    narrow = text(40)  # Too narrow for both side by side.
    start = narrow.index("End-to-end latency")
    assert narrow[start + 1 : start + 9] == [
        "  voice_vision",
        "    First text            712 ms",
        "    First audio frame   1,108 ms",
        "    Response complete   1,840 ms",
        "  text",
        "    First text          6.5 ms",
        "    First audio frame        —",
        "    Response complete        —",
    ]
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
