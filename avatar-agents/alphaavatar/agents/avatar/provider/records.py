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
from collections.abc import Mapping, Sequence
from dataclasses import replace
from hashlib import sha256
from math import isfinite
from types import MappingProxyType
from typing import Any

from alphaavatar.agents.constants import RUNTIME_CONTEXT_TOOL_NAME
from alphaavatar.core.output.schemas import OutputRecordBatch, OutputScope

from .enums import ModelMessagePhase, ModelRole
from .schemas.model_input import (
    ModelAudioPart,
    ModelControlItem,
    ModelFunctionCall,
    ModelFunctionOutput,
    ModelImagePart,
    ModelInputItem,
    ModelInputMessage,
    ModelMediaPart,
    ModelProviderItem,
    ModelReasoningPart,
    ModelRefusalPart,
    ModelTemporalPart,
    ModelTextPart,
)

MODEL_RECORD_SCHEMA = "alphaavatar.model.records.v1"


def _freeze(value: Any, *, depth: int = 0) -> Any:
    if depth > 32:
        raise ValueError("Record metadata exceeds nesting limit")
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("Record metadata must be finite")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("Record metadata requires string keys")
        return MappingProxyType({key: _freeze(v, depth=depth + 1) for key, v in value.items()})
    if isinstance(value, tuple | list):
        return tuple(_freeze(v, depth=depth + 1) for v in value)
    raise TypeError(f"Unsupported record metadata: {type(value).__name__}")


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(v) for key, v in value.items()}
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    return value


def _parts(parts: tuple) -> tuple[tuple, list[dict], int]:
    frozen, content, byte_size = [], [], 0
    for part in parts:
        if isinstance(part, ModelReasoningPart):
            continue
        if isinstance(part, ModelTextPart | ModelRefusalPart):
            if not isinstance(part.text, str):
                raise TypeError("Model text must be str")
            data = {"kind": type(part).__name__, "text": part.text}
            if isinstance(part, ModelTextPart):
                annotations = tuple(_freeze(v) for v in part.annotations)
                part = replace(part, annotations=annotations)
                data["annotations"] = _plain(annotations)
        elif isinstance(part, ModelMediaPart):
            data = {
                "kind": part.kind.value,
                "mime_type": part.mime_type,
                "uri": part.uri,
                "filename": part.filename,
                "data_sha256": sha256(part.data).hexdigest() if part.data is not None else None,
            }
            byte_size += len(part.data or b"")
        elif isinstance(part, ModelImagePart | ModelAudioPart):
            # Retain the Core evidence handle; never encode image/audio buffers on this path.
            data = {"kind": type(part).__name__, "observation_id": part.observation.observation_id}
        elif isinstance(part, ModelTemporalPart):
            data = {
                "kind": "temporal",
                "slices": [
                    {
                        "index": s.index,
                        "start": s.time_range.start.monotonic_ns,
                        "end": s.time_range.end.monotonic_ns,
                        "observations": [o.observation_id for o in s.observations],
                        "events": [e.event_id for e in s.source_events],
                    }
                    for s in part.slices
                ],
            }
        else:
            raise TypeError(f"Unsupported record content: {type(part).__name__}")
        frozen.append(part)
        content.append(data)
    return tuple(frozen), content, byte_size


def model_record_batch(
    *,
    batch_id: str,
    source: str,
    scope: OutputScope,
    items: Sequence[ModelInputItem],
) -> OutputRecordBatch[ModelInputItem] | None:
    """Project immutable evidence; never publish private continuation, policy or user input.

    Binary data is shared as immutable bytes. Core observation parts retain their
    evidence handles. size_bytes accounts encoded fields and inline bytes, not total RSS.
    """
    records, content, size = [], [], 0
    seen = set()
    for item in items:
        if isinstance(item, ModelControlItem | ModelProviderItem):
            continue
        if not isinstance(item, ModelInputMessage | ModelFunctionCall | ModelFunctionOutput):
            raise TypeError("Expected a native model record")
        if not isinstance(item.id, str) or not item.id.strip() or item.id in seen:
            raise ValueError("Record identities must be nonempty and unique within a batch")

        seen.add(item.id)
        data = {"kind": type(item).__name__, "id": item.id, "created_at": item.created_at}

        if isinstance(item, ModelInputMessage):
            if not isinstance(item.role, ModelRole):
                raise TypeError("Expected ModelRole")
            if item.role != ModelRole.ASSISTANT:
                continue
            if item.phase is not None and not isinstance(item.phase, ModelMessagePhase):
                raise TypeError("Expected ModelMessagePhase")
            data.update(
                role=item.role.value,
                phase=item.phase.value if item.phase else None,
                interrupted=item.interrupted,
                transcript_confidence=item.transcript_confidence,
            )
        else:
            if item.name == RUNTIME_CONTEXT_TOOL_NAME:
                continue
            if not all(isinstance(v, str) and v.strip() for v in (item.call_id, item.name)):
                raise ValueError("Tool records require call_id and name")
            data.update(call_id=item.call_id, name=item.name)

        changes = {}

        if isinstance(item, ModelInputMessage | ModelFunctionCall):
            if not isinstance(item.metadata, Mapping):
                raise TypeError("Record metadata must be a mapping")

            changes["metadata"] = _freeze(item.metadata)
            data["metadata"] = _plain(changes["metadata"])

        if isinstance(item, ModelInputMessage | ModelFunctionOutput):
            parts, description, binary_size = _parts(item.parts)
            if not parts and isinstance(item, ModelInputMessage):
                continue

            changes["parts"] = parts
            data["parts"] = description
            size += binary_size

        if isinstance(item, ModelFunctionCall):
            if not isinstance(item.arguments, str):
                raise TypeError("Tool arguments must be serialized text")
            data.update(arguments=item.arguments, group_id=item.group_id)
        elif isinstance(item, ModelFunctionOutput):
            if type(item.is_error) is not bool:
                raise TypeError("Tool result error flag must be bool")
            data["is_error"] = item.is_error

        records.append(replace(item, **changes))
        content.append(data)

    if not records:
        return None

    encoded = json.dumps(
        {"schema": MODEL_RECORD_SCHEMA, "source": source, "records": content},
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode()

    return OutputRecordBatch(
        batch_id=batch_id,
        source=source,
        schema=MODEL_RECORD_SCHEMA,
        scope=scope,
        items=tuple(records),
        digest=sha256(encoded).hexdigest(),
        size_bytes=len(encoded) + size,
    )
