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
from collections.abc import Iterator, Mapping
from math import isfinite
from types import MappingProxyType

type JSONScalar = str | int | float | bool | None
type JSONValue = JSONScalar | tuple[JSONValue, ...] | Mapping[str, JSONValue]

# Identity/control fields are never an extension mechanism, even inside nested maps.
_RESERVED = frozenset(
    """
kind lane scope source payload metadata output identity presentation
session_id event_id sequence created_at monotonic_ns output_id context_id turn_id run_id
request_id item_id call_id producer origin phase content_index chunk_id is_first is_final
source_chunk_id source_chunk_ids alignment_id timing_source start_time_sec end_time_sec
interrupted_output_ids interrupted_run_ids interrupted_turn_ids targets target_lane
target_output_id target_turn_id replacement_output_id replacement_turn_id assistant_output_id
new_turn_id barrier last_audio_sequence last_alignment_sequence affects_scope
mode replace_lane terminal interrupted played_duration_sec pushed_duration_sec queued_duration_sec
control_type playback_type decision_id source_event_id revision audience expires_at expires_at_ns
""".split()
)


class OutputMetadata(Mapping[str, JSONValue]):
    """An immutable, bounded JSON snapshot; never a home for execution semantics.

    Limits include escaped UTF-8 bytes, all containers and all scalar values.
    No payload/media object is traversed. A validated snapshot can be reused per frame.
    """

    __slots__ = ("_values",)
    MAX_DEPTH = 8
    MAX_NODES = 1024
    MAX_BYTES = 16_384
    MAX_ITEMS = 256

    def __init__(self, values: Mapping[str, object] | None = None) -> None:
        if values is None:
            values = {}
        if not isinstance(values, Mapping):
            raise TypeError("Output metadata must be a mapping")
        active: set[int] = set()
        nodes, size = 0, 0

        def charge(count: int) -> None:
            nonlocal size
            size += count
            if size > self.MAX_BYTES:
                raise ValueError("Output metadata exceeds its byte limit")

        def freeze(value: object, depth: int) -> JSONValue:
            nonlocal nodes
            nodes += 1
            if nodes > self.MAX_NODES or depth > self.MAX_DEPTH:
                raise ValueError("Output metadata exceeds its structural limits")
            if value is None or type(value) is bool:
                charge(5)
                return value
            if type(value) is int:
                if not -(2**63) <= value < 2**63:
                    raise ValueError("Metadata integers must fit signed 64 bits")
                charge(len(str(value)))
                return value
            if type(value) is float:
                if not isfinite(value):
                    raise ValueError("Metadata numbers must be finite")
                charge(len(repr(value)))
                return value
            if type(value) is str:
                # Reject overlarge input before allocating an escaped representation.
                if len(value) > self.MAX_BYTES:
                    raise ValueError("Metadata string is too large")
                charge(len(json.dumps(value, ensure_ascii=False).encode("utf-8")))
                return value
            if isinstance(value, Mapping) or type(value) in (list, tuple):
                if id(value) in active:
                    raise ValueError("Metadata cannot contain cycles")
                if len(value) > self.MAX_ITEMS:
                    raise ValueError("Metadata container is too large")
                active.add(id(value))
                charge(2 + 2 * len(value))
                try:
                    if isinstance(value, Mapping):
                        result = {}
                        for key, item in value.items():
                            if type(key) is not str or not key or len(key) > 128:
                                raise ValueError("Metadata keys must be bounded nonempty strings")
                            if key in _RESERVED:
                                raise ValueError(f"Reserved output metadata key: {key}")
                            charge(len(json.dumps(key, ensure_ascii=False).encode("utf-8")))
                            result[key] = freeze(item, depth + 1)
                        return MappingProxyType(result)
                    return tuple(freeze(item, depth + 1) for item in value)
                finally:
                    active.remove(id(value))
            raise TypeError(f"Unsupported metadata value: {type(value).__name__}")

        object.__setattr__(self, "_values", freeze(values, 0))

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("Output metadata is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("Output metadata is immutable")

    def __getitem__(self, key: str) -> JSONValue:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


EMPTY_METADATA = OutputMetadata()


def freeze_metadata(values: Mapping[str, object] | None = None) -> OutputMetadata:
    if type(values) is OutputMetadata:
        return values

    return EMPTY_METADATA if values is None else OutputMetadata(values)
