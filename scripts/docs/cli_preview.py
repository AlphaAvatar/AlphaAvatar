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
"""docs/cli/cli.html from terminal recordings: what each command shows, colors and all.

    python scripts/docs/cli_preview.py record OUT COLS [--answer TEXT ...]
        [--interrupt-at TEXT] -- COMMAND...
    python scripts/docs/cli_preview.py html OUT [--mask PATH=NAME ...] PANEL...

``record`` runs a command in a terminal of COLS columns and writes OUT.cast (asciinema v2:
each output chunk with its time) and OUT.ansi (the bytes as shown). Each --answer goes to the
next prompt (output ending in ": "); with --interrupt-at, Ctrl+C is typed once the output ends
with that text. ``html`` writes one self-contained page, openable offline: each PANEL is
``NAME|FILE.ansi|TITLE|EXIT[|LABEL]``, the screen a terminal shows once the command ends, its
escape codes as colors. A LABEL, such as the offline test doubles a measured run used, is shown
beside its panel; each --mask shows PATH, a recording machine's directory, as NAME.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
from pathlib import Path

SGR = re.compile(r"\x1b\[([0-9;]*)m")
ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# The terminal's own palette for the 4-bit codes the CLI uses; truecolor codes are exact.
BASIC = {"31": "#f87171", "32": "#4ade80", "33": "#facc15", "90": "#9ca3af"}


def record(
    out: str, cols: int, answers: list[str], interrupt: str | None, command: list[str]
) -> int:
    import fcntl
    import pty
    import struct
    import termios

    pid, fd = pty.fork()
    if pid == 0:
        os.environ.pop("COLUMNS", None)
        os.environ["TERM"] = "xterm-256color"
        os.execvp(command[0], command)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 48, cols, 0, 0))
    start, events, shown, seen = time.monotonic(), [], b"", b""
    stop = interrupt.encode() if interrupt else None
    while True:
        try:
            data = os.read(fd, 4096)
        except OSError:
            break
        if not data:
            break
        events.append([round(time.monotonic() - start, 6), "o", data.decode("utf-8", "replace")])
        shown += data
        seen += data
        plain = re.sub(rb"\x1b\[[0-9;]*[A-Za-z]", b"", seen)  # A prompt may be painted.
        if stop is not None and plain.endswith(stop):
            time.sleep(0.3)
            os.write(fd, b"\x03")
            stop, seen = None, b""
        elif plain.endswith(b": ") and answers:
            time.sleep(0.2)
            os.write(fd, answers.pop(0).encode() + b"\n")
            seen = b""
    code = os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1])
    header = {"version": 2, "width": cols, "height": 48, "env": {"TERM": "xterm-256color"}}
    with open(f"{out}.cast", "w", encoding="utf-8") as cast:
        cast.write(json.dumps(header) + "\n")
        for event in events:
            cast.write(json.dumps(event, ensure_ascii=False) + "\n")
    Path(f"{out}.ansi").write_bytes(shown)
    return code


def screen(data: str) -> str:
    """What the terminal shows at the end: carriage returns and line erases applied."""
    lines, line = [], ""
    for token in re.split(r"(\r\n|\n|\r|\x1b\[K)", data):
        if token in ("\n", "\r\n"):
            lines.append(line)
            line = ""
        elif token == "\r":
            line = ""  # Back to the line's start: what follows replaces it.
        elif token != "\x1b[K":
            line += token
    lines.append(line)
    return "\n".join(lines).strip("\n")


def colored(text: str) -> str:
    out, color, bold, last = [], None, False, 0
    for match in SGR.finditer(text):
        out.append(span(text[last : match.start()], color, bold))
        last = match.end()
        codes = match.group(1).split(";") if match.group(1) else ["0"]
        index = 0
        while index < len(codes):
            code = codes[index]
            if code == "0":
                color, bold = None, False
            elif code == "1":
                bold = True
            elif code in BASIC:
                color = BASIC[code]
            elif code == "38" and codes[index + 1 : index + 2] == ["2"]:
                color = "rgb({},{},{})".format(*codes[index + 2 : index + 5])
                index += 4
            index += 1
    out.append(span(text[last:], color, bold))
    return "".join(out)


def span(text: str, color: str | None, bold: bool) -> str:
    if not text:
        return ""
    escaped = html.escape(ESCAPE.sub("", text))
    style = ";".join(filter(None, (f"color:{color}" if color else "", "font-weight:700" * bold)))
    return f'<span style="{style}">{escaped}</span>' if style else escaped


def page(panels: list[str], masks: dict[str, str]) -> str:
    index, sections = [], []
    for panel in panels:
        name, path, title, code, *label = panel.split("|")
        cols = int(re.search(r"-(\d+)$", Path(path).stem).group(1))
        text = screen(Path(path).read_bytes().decode("utf-8", "replace"))
        for old, new in masks.items():
            text = text.replace(old, new)
        body = colored(text)
        tag = f'<span class="tag">{html.escape(label[0])}</span>' if label else ""
        index.append(f'<li><a href="#{name}">{html.escape(title)}</a>{tag}</li>')
        sections.append(
            f'<section id="{name}"><h2>{html.escape(title)}{tag}</h2>'
            f'<p class="meta"><span>{cols} columns</span><span>exit {html.escape(code)}</span></p>'
            f'<div class="term"><pre style="width:{cols}ch">{body}</pre></div></section>'
        )
    return TEMPLATE.replace("{index}", "\n".join(index)).replace("{panels}", "\n".join(sections))


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AlphaAvatar CLI Output</title>
<style>
/* One reading column; each terminal keeps its own width and scrolls inside. System fonts
   only: the page opens offline. */
:root {
  --page: #f6f7f9; --ink: #1c2128; --muted: #5a6470; --accent: #2f6fb3; --tag: #7a4b00;
  --tag-bg: #fdf1d8; --term: #0d1117; --term-ink: #e6edf3; --term-rule: #30363d;
  --sans: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
}
@media (prefers-color-scheme: dark) {
  :root { --page: #0b0e12; --ink: #e3e8ee; --muted: #9aa5b1; --accent: #7cb4f0;
    --tag: #f5c777; --tag-bg: #3a2c10; color-scheme: dark; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink); font: 15px/1.55 var(--sans); }
main { max-width: 1000px; margin: 0 auto; padding: 28px 16px 72px; }
h1 { font-size: 24px; line-height: 1.25; margin: 0 0 6px; }
.lead { color: var(--muted); max-width: 70ch; margin: 0 0 18px; }
nav ol { columns: 2 280px; margin: 0; padding-left: 20px; color: var(--muted); font-size: 14px; }
nav a { color: var(--accent); text-decoration: none; }
nav a:hover, nav a:focus-visible { text-decoration: underline; }
section { margin-top: 34px; }
h2 { font-size: 16px; line-height: 1.35; margin: 0 0 4px; }
.tag { display: inline-block; margin-left: 8px; padding: 0 7px; border-radius: 4px;
  background: var(--tag-bg); color: var(--tag); font-size: 12px; font-weight: 600; }
.meta { display: flex; gap: 14px; color: var(--muted); font-size: 13px; margin: 0 0 10px; }
.term { background: var(--term); color: var(--term-ink); border: 1px solid var(--term-rule);
  border-radius: 6px; padding: 14px 16px; overflow-x: auto; }
.term pre { margin: 0; font: 13px/1.5 var(--mono); white-space: pre; min-width: max-content; }
</style>
</head>
<body>
<main>
<h1>AlphaAvatar CLI output</h1>
<p class="lead">What a terminal of each width shows once the command ends, rendered from its
recording with the escape codes kept as colors (scripts/docs/cli_preview.py). Setup, config,
and Doctor declined or with --no-metrics ran on a clean Ubuntu 24.04 root with the Linux
package of this build. Doctor's measured runs used the offline test doubles of its tests,
marked 离线测试替身: their services and model files are stand-ins and their timings are the
doubles', in rounds of their own. No panel here holds a real service's figures: those are
recorded apart, in the acceptance log. Every figure ends at the Host's output; LiveKit's
transport, a client's playback and the devices are measured separately. Lines wider than a
panel are diagnostics and commands, which print whole.</p>
<nav><ol>
{index}
</ol></nav>
{panels}
</main>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    recording = commands.add_parser("record")
    recording.add_argument("out")
    recording.add_argument("cols", type=int)
    recording.add_argument("--answer", action="append", default=[])
    recording.add_argument("--interrupt-at")
    building = commands.add_parser("html")
    building.add_argument("out")
    building.add_argument("--mask", action="append", default=[], metavar="PATH=NAME")
    building.add_argument("panels", nargs="+")
    argv = sys.argv[1:]
    command = argv[argv.index("--") + 1 :] if "--" in argv else []
    args = parser.parse_args(argv[: argv.index("--")] if "--" in argv else argv)
    if args.command == "record":
        code = record(args.out, args.cols, args.answer, args.interrupt_at, command)
        print(f"[{args.out}: exit {code}, {args.cols} columns]", file=sys.stderr)
        return code
    masks = dict(mask.split("=", 1) for mask in args.mask)
    Path(args.out).write_text(page(args.panels, masks), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
