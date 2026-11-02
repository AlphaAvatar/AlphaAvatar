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
"""Configuration commands: no Host, runner, model, client, workspace or log socket.

Output styling only touches already redacted, control-character cleaned text, renders it
literally and never wraps it. JSON and redirected output stay plain.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Sequence
from typing import TextIO

from alphaavatar.core.log.diagnostics import format_error
from alphaavatar.host.log.format import (
    BOLD,
    BRAND_BLUE,
    DIM,
    GREEN,
    RED,
    RESET,
    SIGNAL_CYAN,
    use_color,
)

SCOPE = "configuration and read-only path checks"
_LINE = re.compile(
    r"(?P<lead>\s*(?:- )*)"
    r"(?:(?P<key>'(?:[^']|'')*'|\"(?:[^\"\\]|\\.)*\"|[^\s'\"#][^:]*?):(?= |$))?"
    r"(?P<value>.*)"
)
_PLAIN = re.compile(
    r"true|false|null|~|[-+]?\d[\d_]*(?:\.\d*)?(?:[eE][-+]?\d+)?|[-+]?\.(?:inf|nan)"
)
_MARKERS = ("'[hidden]'", "'[redacted]'")


def _paint(text: str, style: str, color: bool) -> str:
    return f"{style}{text}{RESET}" if color and text else text


def _open_quote(value: str) -> str | None:
    """The quote a multi-line scalar leaves open; its continuation lines are not keys."""
    value = value.strip()
    for quote in "'\"":
        if value.startswith(quote):
            inner = value[1:].replace(quote * 2, "") if quote == "'" else value[1:]
            return None if inner.endswith(quote) and len(value) > 1 else quote
    return None


def _highlight(yaml_text: str) -> str:
    lines, quote = [], None
    for line in yaml_text.splitlines():
        if quote is not None:
            lines.append(line)
            if line.rstrip().endswith(quote) and not line.rstrip().endswith(quote * 2):
                quote = None
            continue
        match = _LINE.fullmatch(line)
        lead, key, value = match["lead"], match["key"], match["value"]
        scalar = value.lstrip(" ")
        rendered = lead + (f"{BRAND_BLUE}{key}{RESET}:" if key is not None else "")
        rendered += value[: len(value) - len(scalar)]
        if scalar in _MARKERS:
            rendered += _paint(scalar, DIM, True)
        elif _PLAIN.fullmatch(scalar):
            rendered += _paint(scalar, SIGNAL_CYAN, True)
        else:
            rendered += scalar
            quote = _open_quote(scalar)
        lines.append(rendered)
    return "\n".join(lines) + "\n"


def _status(label: str, style: str, message: str, stream: TextIO) -> None:
    color = use_color("auto", stream)
    print(f"{_paint(label, BOLD + style, color)}  {message}", file=stream)


def _load(path: str, overrides: Sequence[str]):
    from alphaavatar.agents.env import init_env
    from alphaavatar.host.configs.loader import check_application_paths, load_application

    init_env()  # The same .env the start command reads for <ENV_VAR> placeholders.
    config = load_application(path, overrides)
    check_application_paths(config)
    return config


def _failed(error: Exception, *, as_json: bool) -> int:
    from alphaavatar.host.configs.view import describe_error

    if as_json:
        print(json.dumps({"valid": False, "error": describe_error(error)}, indent=2))
        return 2
    color = use_color("auto", sys.stderr)
    _status("ERROR", RED, f"{SCOPE} failed", sys.stderr)
    for line in format_error(error).splitlines():
        # Code locations are auxiliary; the failing fields stay prominent.
        auxiliary = line.lstrip().startswith(("at ", "additional"))
        print(_paint(line, DIM, color) if auxiliary else line, file=sys.stderr)
    return 2


def check(path: str, overrides: Sequence[str], *, as_json: bool) -> int:
    try:
        from alphaavatar.host.configs.view import describe_summary

        summary = describe_summary(_load(path, overrides))
    except Exception as error:
        return _failed(error, as_json=as_json)
    if as_json:
        print(json.dumps({"valid": True, **summary}, indent=2, ensure_ascii=False))
        return 0
    color = use_color("auto", sys.stdout)
    _status("OK", GREEN, f"{SCOPE} passed", sys.stdout)
    width = max(map(len, summary))
    for key, value in summary.items():
        print(f"    {_paint(key.ljust(width), DIM, color)}  {value}")
    return 0


def show(path: str, overrides: Sequence[str], *, as_json: bool) -> int:
    try:
        from alphaavatar.host.configs.view import describe_application

        view = describe_application(_load(path, overrides))
    except Exception as error:
        return _failed(error, as_json=as_json)
    if as_json:
        print(json.dumps(view, indent=2, ensure_ascii=False))
        return 0
    import yaml

    # No folding: long paths and text stay on one line, ready to copy.
    text = yaml.safe_dump(view, sort_keys=False, allow_unicode=True, width=float("inf"))
    print(_highlight(text) if use_color("auto", sys.stdout) else text, end="")
    return 0


def init(path: str, *, avatar_id: str) -> int:
    from alphaavatar.host.configs.template import REQUIRED_ENVIRONMENT, write_template

    try:
        target = write_template(path, avatar_id=avatar_id)
    except FileExistsError:
        print(f"Refusing to overwrite an existing file: {path}", file=sys.stderr)
        return 2
    except Exception as error:
        print(f"Cannot create the configuration:\n{format_error(error)}", file=sys.stderr)
        return 2
    print(f"Created {target}")
    print("Set these in the environment or .env (never in the file):")
    print("\n".join(f"  {name:<50} {use}" for name, use in REQUIRED_ENVIRONMENT))
    print(f"Then run: alphaavatar check {path}")
    return 0
