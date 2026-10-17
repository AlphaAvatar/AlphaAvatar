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

import re
import sys
from collections import deque
from types import TracebackType

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*")
_IMPORT_SYMBOL = re.compile(r"cannot import name ['\"]([A-Za-z_][A-Za-z_0-9]*)['\"] from ")
_MAX_ERRORS = 8
_MAX_FRAMES = 12
_MAX_FIELDS = 16
_MAX_LOCATION_DEPTH = 12


def _identifier(value: object) -> str:
    if isinstance(value, str) and len(value) <= 256 and _IDENTIFIER.fullmatch(value):
        return value
    return "?"


def _locations(error: BaseException) -> tuple[str, ...]:
    # Reporting a failed import must not try to import Pydantic again.
    for name in ("pydantic", "pydantic_core"):
        module = sys.modules.get(name)
        validation_error = vars(module).get("ValidationError") if module is not None else None
        if isinstance(validation_error, type) and isinstance(error, validation_error):
            break
    else:
        return ()
    try:
        rows = error.errors(include_url=False, include_context=False, include_input=False)
    except (TypeError, ValueError):
        return ()
    locations = []
    for row in rows[:_MAX_FIELDS]:
        parts = [
            str(part) if type(part) is int else _identifier(part)
            for part in row["loc"][:_MAX_LOCATION_DEPTH]
        ]
        locations.append(".".join(parts) or "<root>")
    return tuple(locations)


def _frames(traceback: TracebackType | None) -> tuple[str, ...]:
    frames: deque[str] = deque(maxlen=_MAX_FRAMES)
    while traceback is not None:
        frame = traceback.tb_frame
        module = _identifier(frame.f_globals.get("__name__"))
        function = frame.f_code.co_name
        if not module.startswith(("importlib.", "_frozen_importlib")):
            function = function if function == "<module>" else _identifier(function)
            frames.append(f"    at {module}:{traceback.tb_lineno} in {function}")
        traceback = traceback.tb_next
    return tuple(frames)


def format_error(error: BaseException, *, details: bool = False) -> str:
    """Bounded diagnostic metadata, without exception values, source lines or locals."""
    pending = deque((("error", error),))
    seen: set[int] = set()
    lines: list[str] = []
    while pending and len(seen) < _MAX_ERRORS:
        relation, current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        name = _identifier(type(current).__name__)
        fields = [f"  {relation}: {name}"]
        if isinstance(current, ImportError):
            fields.append(f"module={_identifier(current.name)}")
            message = current.msg[:4096] if isinstance(current.msg, str) else ""
            symbol = _IMPORT_SYMBOL.match(message)
            if symbol is not None:
                fields.append(f"symbol={_identifier(symbol[1])}")
            if "partially initialized module" in message and symbol is not None:
                fields.append("circular_import=True")
        elif isinstance(current, OSError) and type(current.errno) is int:
            fields.append(f"errno={current.errno}")
        lines.append(" ".join(fields))
        locations = _locations(current)
        if locations:
            lines.append(f"    fields: {', '.join(locations)}")
        frames = _frames(current.__traceback__)
        lines.extend(frames if details else frames[-1:])
        cause = current.__cause__
        if cause is None and not current.__suppress_context__:
            cause = current.__context__
        if cause is not None:
            pending.append(("caused by", cause))
        if isinstance(current, BaseExceptionGroup):
            # Reserve traversal for this branch, not queued siblings, so a leaf cause
            # is visible before the output budget is consumed by wrapper groups.
            room = _MAX_ERRORS - len(seen)
            pending.extend(
                ("group member", item) for item in reversed(current.exceptions[: max(0, room)])
            )
            if len(current.exceptions) > max(0, room):
                lines.append("    additional group members omitted")
    if pending:
        lines.append("  additional exception details omitted")
    return "\n".join(lines)
