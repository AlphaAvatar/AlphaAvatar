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
"""docs/cli/cli.html and its translations from terminal recordings: what each command shows,
colors and all.

    python scripts/docs/cli_preview.py record OUT COLS [--answer TEXT ...]
        [--interrupt-at TEXT] -- COMMAND...
    python scripts/docs/cli_preview.py screen DATA NAME OUT EXIT [--mask PATH=NAME ...]
    python scripts/docs/cli_preview.py html DATA

``record`` runs a command in a terminal of COLS columns and writes OUT.cast (asciinema v2:
each output chunk with its time) and OUT.ansi (the bytes as shown). Each --answer goes to the
next prompt (output ending in ": "); with --interrupt-at, Ctrl+C is typed once the output ends
with that text. ``screen`` keeps, as panel NAME of DATA (docs/cli/cli-output.json), the screen
a terminal shows once that recording ends, its escape codes kept for colors, with its width and
EXIT code; each --mask shows PATH, a recording machine's directory, as NAME. A panel's title and
optional LABEL (such as the offline test doubles a measured run used) are written in DATA, once
per page language. ``html`` writes every page DATA lists, beside DATA: one self-contained page
per language, openable offline, all of them from the same panels.
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
    """What the terminal shows at the end: carriage returns and line erases applied, and a
    list's redrawing, the cursor moved up and everything below it erased; the cursor's hiding
    and showing dropped."""
    lines, row = [""], 0
    for token in re.split(r"(\r\n|\n|\r|\x1b\[K|\x1b\[\d*A|\x1b\[J|\x1b\[\?25[hl])", data):
        if token in ("\n", "\r\n"):
            row += 1
            if row == len(lines):
                lines.append("")
            else:
                lines[row] = ""  # Written over from its start.
        elif token == "\r":
            lines[row] = ""  # Back to the line's start: what follows replaces it.
        elif up := re.fullmatch(r"\x1b\[(\d*)A", token):
            row = max(row - int(up.group(1) or 1), 0)
        elif token == "\x1b[J":
            del lines[row + 1 :]
        elif token not in ("\x1b[K", "\x1b[?25h", "\x1b[?25l"):
            lines[row] += token
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


def page(data: dict, lang: str) -> str:
    text = next(p for p in data["pages"] if p["lang"] == lang)
    links = [
        f'<a href="{p["file"]}">{html.escape(p["name"])}</a>'
        for p in data["pages"]
        if p["lang"] != lang
    ]
    index, sections = [], []
    for panel in data["panels"]:
        name, title = panel["name"], html.escape(panel["title"][lang])
        tag = (
            f'<span class="tag">{html.escape(panel["label"][lang])}</span>'
            if "label" in panel
            else ""
        )
        columns = html.escape(text["columns"].format(panel["columns"]))
        code = html.escape(text["exit"].format(panel["exit"]))
        index.append(f'<li><a href="#{name}">{title}</a>{tag}</li>')
        sections.append(
            f'<section id="{name}"><h2>{title}{tag}</h2>'
            f'<p class="meta"><span>{columns}</span><span>{code}</span></p>'
            f'<div class="term"><pre style="width:{panel["columns"]}ch">{colored(panel["screen"])}</pre></div></section>'
        )
    values = {
        "lang": lang,
        "title": html.escape(text["title"]),
        "heading": html.escape(text["heading"]),
        "links": " · ".join(links),
        "lead": text["lead"],
        "index": "\n".join(index),
        "panels": "\n".join(sections),
    }
    return re.sub(r"\{(\w+)\}", lambda m: values[m.group(1)], TEMPLATE)


def store(data_path: Path, name: str, out: str, code: str, masks: dict[str, str]) -> None:
    data = json.loads(data_path.read_text(encoding="utf-8"))
    header = json.loads(Path(f"{out}.cast").read_text(encoding="utf-8").splitlines()[0])
    text = screen(Path(f"{out}.ansi").read_bytes().decode("utf-8", "replace"))
    for old, new in masks.items():
        text = text.replace(old, new)
    panel = next((p for p in data["panels"] if p["name"] == name), None)
    if panel is None:
        panel = {"name": name, "title": {p["lang"]: name for p in data["pages"]}}
        data["panels"].append(panel)
    panel.update(columns=header["width"], exit=code, screen=text)
    data_path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


TEMPLATE = """<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
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
<h1>{heading}</h1>
<p>{links}</p>
<p class="lead">{lead}</p>
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
    storing = commands.add_parser("screen")
    storing.add_argument("data", type=Path)
    storing.add_argument("name")
    storing.add_argument("out")
    storing.add_argument("exit")
    storing.add_argument("--mask", action="append", default=[], metavar="PATH=NAME")
    building = commands.add_parser("html")
    building.add_argument("data", type=Path)
    argv = sys.argv[1:]
    command = argv[argv.index("--") + 1 :] if "--" in argv else []
    args = parser.parse_args(argv[: argv.index("--")] if "--" in argv else argv)
    if args.command == "record":
        code = record(args.out, args.cols, args.answer, args.interrupt_at, command)
        print(f"[{args.out}: exit {code}, {args.cols} columns]", file=sys.stderr)
        return code
    if args.command == "screen":
        store(args.data, args.name, args.out, args.exit, dict(m.split("=", 1) for m in args.mask))
        return 0
    data = json.loads(args.data.read_text(encoding="utf-8"))
    for text in data["pages"]:
        (args.data.parent / text["file"]).write_text(page(data, text["lang"]), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
