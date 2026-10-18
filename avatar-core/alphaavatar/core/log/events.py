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

import json
import logging
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from itertools import islice
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .records import Redactor

LABELS = {
    "engine.ready": "READY",
    "input.committed": "USER INPUT",
    "run.started": "RUN START",
    "model.started": "MODEL START",
    "model.first_text": "FIRST TEXT",
    "model.completed": "MODEL COMPLETE",
    "assistant.message": "ASSISTANT OUTPUT",
    "tool.started": "TOOL START",
    "tool.finished": "TOOL END",
    "run.finished": "RUN END",
    "text.started": "TEXT SENT",
    "text.finished": "TEXT CLOSED",
}
TRACE_EVENTS = frozenset(("core.event", "core.gap"))
LABELS.update({"core.event": "CORE EVENT", "core.gap": "CORE GAP"})
_FIELDS = frozenset(
    (
        "session_id context_id turn_id input_id run_id request_id response_id item_id output_id "
        "call_id model backend provider modality state phase reason outcome error_type model_step "
        "tool_round tool_name executed interrupted elapsed_ms model_steps tool_rounds stage "
        "refusal text_chars parts_truncated content_index output_items input_tokens output_tokens "
        "stream event_id sequence event_time_ns observed_time_ns event_kind observation_id "
        "annotation_id source_id source_generation source_kind producer lane control_type "
        "playback_type played_seconds pushed_seconds queued_seconds alignment_id target_count "
        "item_count batch_id schema missed_count first_sequence cutoff_sequence delivery "
        "measurement "
        "start_seconds end_seconds timing_source chunk_id source_chunk_id source_chunk_count"
    ).split()
)
MAX_FIELDS = 24
MAX_FIELD_CHARS = 256
MAX_CONTENT_CHARS = 4096


def validate_fields(values: object) -> None:
    if type(values) is not dict or len(values) > MAX_FIELDS or values.keys() - _FIELDS:
        raise ValueError("Invalid conversation diagnostic fields")
    for value in values.values():
        if value is None or type(value) is bool:
            continue
        if type(value) is str and len(value) <= MAX_FIELD_CHARS:
            continue
        if type(value) is int and -(2**63) <= value < 2**63:
            continue
        if type(value) is float and math.isfinite(value):
            continue
        raise ValueError("Invalid conversation diagnostic value")


def safe_fields(values: Mapping, redactor: Redactor) -> dict:
    # Validate again on the receiver; authentication is not permission to bypass limits.
    values = dict(values)
    validate_fields(values)
    return {
        key: redactor(value)[:MAX_FIELD_CHARS] if isinstance(value, str) else value
        for key, value in values.items()
        if value is not None
    }


@dataclass(frozen=True, slots=True)
class ConversationEvent:
    name: str
    fields: dict
    parts: tuple[str, ...] = field(default=(), repr=False)
    parts_truncated: bool = False

    def __str__(self) -> str:
        # Other logging handlers must not get private content from normal string formatting.
        return f"{LABELS.get(self.name, 'CONVERSATION')} [content omitted]"

    def preview(self, redactor: Redactor, *, limit: int) -> tuple[str | None, bool]:
        if not self.parts:
            return None, False
        # Extra lookahead lets credential filtering finish before the display is truncated.
        remaining = limit + 4096
        chunks = []
        clipped = self.parts_truncated
        for index, part in enumerate(self.parts):
            if index:
                if not remaining:
                    clipped = True
                    break
                chunks.append("\n")
                remaining -= 1
            chunks.append(part[:remaining])
            if len(part) > remaining:
                clipped = True
                break
            remaining -= len(part)
        text = redactor("".join(chunks))
        return text[:limit], clipped or len(text) > limit


def log_event(
    logger: logging.Logger,
    name: str,
    *,
    text: str | None = None,
    text_parts: Iterable[str] = (),
    level: int = logging.INFO,
    **fields,
) -> None:
    """A bounded, best-effort observation; never an execution or delivery acknowledgement."""
    if not logger.isEnabledFor(level):
        return
    try:
        if name not in LABELS:
            raise ValueError("Unknown conversation diagnostic event")
        if name in TRACE_EVENTS:
            # Runtime tracing never accepts payload bodies, even with conversation content enabled.
            text, text_parts = None, ()
        parts = (text,) if text is not None else tuple(islice(text_parts, 65))
        if any(type(part) is not str for part in parts):
            raise TypeError("Conversation previews must contain text only")
        clipped, parts = len(parts) > 64, parts[:64]
        if parts:
            fields["text_chars"] = sum(map(len, parts)) + len(parts) - 1
            if clipped:
                fields["parts_truncated"] = True
        # Clip only metadata here; content is not serialized until the Host policy allows it.
        values = {
            key: value[:MAX_FIELD_CHARS] if type(value) is str else value
            for key, value in fields.items()
            if value is not None
        }
        validate_fields(values)
        logger.log(level, ConversationEvent(name, values, parts, clipped), stacklevel=2)
    except Exception:
        # Even a failing external logging handler cannot change the business operation.
        return


def render_event(name: str, fields: Mapping, content: str | None, truncated: bool) -> str:
    header = " ".join(
        f"{key}={json.dumps(value, ensure_ascii=False)}" for key, value in fields.items()
    )
    lines = [f"{LABELS[name]} {header}".rstrip()]
    if content is not None:
        suffix = " [truncated]" if truncated else ""
        lines.append(f"  text={json.dumps(content, ensure_ascii=False)}{suffix}")
    return "\n".join(lines)
