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

import hashlib
import math
import re
import secrets
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from itertools import count
from threading import Lock

_MAX_FIELDS = 32
_MAX_ID_CHARS = 256
_MAX_CODE_CHARS = 64
_MAX_INTEGER = 2**63 - 1
_CODE = re.compile(r"[a-z][a-z0-9_.-]*\Z", re.ASCII)
_CODE_FIELDS = frozenset(("action", "state", "outcome", "reason"))
_FIELDS = frozenset(
    (
        "source_id source_generation input_source_id input_source_generation "
        "segment_id observation_id event_id annotation_id "
        "candidate_id candidate_revision decision_id turn_id input_id provider_item_id stream_id "
        "sequence stream_sequence first_stream_sequence last_stream_sequence frame_count "
        "text_chars evidence_count missing_count missed_count cutoff_sequence "
        "start_cutoff_sequence event_time_ns observed_time_ns start_time_ns end_time_ns "
        "route_index evicted_count duplicate_count retired_evictions action state outcome reason"
    ).split()
)


def _is_code(value: object) -> bool:
    return type(value) is str and 0 < len(value) <= _MAX_CODE_CHARS and bool(_CODE.fullmatch(value))


def _object_size(values: dict) -> int:
    # Only validated ASCII codes, hashed IDs and bounded numbers reach this calculation.
    size = 2 + max(0, len(values) - 1)
    for key, value in values.items():
        scalar_size = (
            4 if value is None else len(value) + 2 if type(value) is str else len(str(value))
        )
        size += len(key) + 3 + scalar_size
    return size


@dataclass(frozen=True, slots=True)
class InputTracePolicy:
    max_records: int = 512
    max_bytes: int = 256 * 1024
    ttl_sec: float = 120.0
    max_record_bytes: int = 2048
    max_frozen: int = 2
    max_frozen_bytes: int = 512 * 1024
    frozen_ttl_sec: float = 300.0

    def __post_init__(self) -> None:
        for name, minimum in (
            ("max_records", 1),
            ("max_bytes", 2),
            ("max_record_bytes", 1),
            ("max_frozen", 0),
            ("max_frozen_bytes", 0),
        ):
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= _MAX_INTEGER:
                raise ValueError(f"Invalid input trace policy: {name}")
        for name in ("ttl_sec", "frozen_ttl_sec"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not 0 < value <= _MAX_INTEGER / 1e9:
                raise ValueError(f"Invalid input trace policy: {name}")


@dataclass(frozen=True, slots=True)
class _TraceRecord:
    trace_sequence: int
    recorded_time_ns: int
    stage: str
    fields: tuple[tuple[str, str | int], ...]
    size_bytes: int

    def to_dict(self) -> dict:
        return {
            "trace_sequence": self.trace_sequence,
            "recorded_time_ns": self.recorded_time_ns,
            "stage": self.stage,
            **dict(self.fields),
        }


@dataclass(frozen=True, slots=True)
class InputTraceSnapshot:
    captured_time_ns: int
    records: tuple[_TraceRecord, ...]
    counters: tuple[tuple[str, int], ...]
    next_trace_sequence: int
    retained_bytes: int
    reason: str | None = None
    frozen: tuple[InputTraceSnapshot, ...] = ()
    frozen_bytes: int = 0

    def _metadata(self) -> dict:
        return {
            "schema": "alphaavatar.input_trace.v1",
            "captured_time_ns": self.captured_time_ns,
            "reason": self.reason,
            "first_trace_sequence": self.records[0].trace_sequence if self.records else None,
            "last_trace_sequence": self.records[-1].trace_sequence if self.records else None,
            "next_trace_sequence": self.next_trace_sequence,
            "retained_bytes": self.retained_bytes,
            "frozen_bytes": self.frozen_bytes,
        }

    def _size_bytes(self) -> int:
        envelope = {**self._metadata(), "counters": None, "records": None, "frozen": None}
        frozen_size = 2 + max(0, len(self.frozen) - 1) + self.frozen_bytes
        return (
            _object_size(envelope)
            - 12
            + _object_size(dict(self.counters))
            + self.retained_bytes
            + frozen_size
        )

    def to_dict(self) -> dict:
        return {
            **self._metadata(),
            "counters": dict(self.counters),
            "records": [record.to_dict() for record in self.records],
            "frozen": [snapshot.to_dict() for snapshot in self.frozen],
        }


@dataclass(frozen=True, slots=True)
class _FrozenTrace:
    snapshot: InputTraceSnapshot
    size_bytes: int


class InputTrace:
    """Bounded metadata-only evidence, without I/O, serialization or background tasks on record.

    Byte limits cover compact ASCII JSON, not Python object overhead. Expiry is checked on access;
    previously returned snapshots belong to the caller. Oversized records are dropped and counted
    as truncated. Record sequence gaps and counters expose loss; this is not a delivery ledger.
    """

    def __init__(
        self, policy: InputTracePolicy | None = None, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.policy = policy if policy is not None else InputTracePolicy()
        if not isinstance(self.policy, InputTracePolicy):
            raise TypeError("Expected an InputTracePolicy")
        self._clock = clock
        self._lock = Lock()
        self._contentions = count()
        self._contention_samples = 0
        self._salt = secrets.token_bytes(32)
        self._records: deque[_TraceRecord] = deque()
        self._frozen: deque[_FrozenTrace] = deque()
        self._record_bytes = 0
        self._frozen_bytes = 0
        self._next_sequence = 1
        self._last_time_ns = 0
        self._ttl_ns = int(self.policy.ttl_sec * 1e9)
        self._frozen_ttl_ns = int(self.policy.frozen_ttl_sec * 1e9)
        self._counters = dict.fromkeys(
            (
                "recorded_count",
                "evicted_count",
                "expired_count",
                "invalid_count",
                "truncated_count",
                "contention_count",
                "frozen_count",
                "frozen_evicted_count",
                "frozen_expired_count",
                "frozen_dropped_count",
            ),
            0,
        )

    def _now(self) -> int:
        try:
            value = self._clock()
            if type(value) not in (int, float) or not 0 <= value <= _MAX_INTEGER / 1e9:
                raise ValueError("Invalid input trace clock")
            if not math.isfinite(value):
                raise ValueError("Invalid input trace clock")
            self._last_time_ns = max(self._last_time_ns, int(value * 1e9))
        except Exception:
            self._counters["invalid_count"] += 1
        return self._last_time_ns

    def _expire(self, now: int) -> None:
        while self._records and self._records[0].recorded_time_ns <= now - self._ttl_ns:
            self._record_bytes -= self._records.popleft().size_bytes + 1
            self._counters["expired_count"] += 1
        while (
            self._frozen and self._frozen[0].snapshot.captured_time_ns <= now - self._frozen_ttl_ns
        ):
            self._frozen_bytes -= self._frozen.popleft().size_bytes
            self._counters["frozen_expired_count"] += 1

    def record(self, stage: str, **fields: object) -> None:
        if not self._lock.acquire(blocking=False):
            # CPython's count increment is atomic; missing evidence is not a business failure.
            next(self._contentions)
            return
        try:
            sequence = self._next_sequence
            self._next_sequence += 1
            now = self._now()
            self._expire(now)
            if type(stage) is str and len(stage) > _MAX_CODE_CHARS or len(fields) > _MAX_FIELDS:
                self._counters["truncated_count"] += 1
                return
            if not _is_code(stage) or fields.keys() - _FIELDS:
                self._counters["invalid_count"] += 1
                return
            values: dict[str, str | int] = {}
            for key, value in fields.items():
                if value is None:
                    continue
                if key.endswith("_id"):
                    if type(value) is str and len(value) > _MAX_ID_CHARS:
                        self._counters["truncated_count"] += 1
                        return
                    if type(value) is not str or not value:
                        raise ValueError("Invalid input trace identity")
                    # The field name is deliberately excluded: one identity joins across stages.
                    values[key] = (
                        "id_"
                        + hashlib.blake2b(
                            value.encode("utf-8"), key=self._salt, digest_size=16
                        ).hexdigest()
                    )
                elif key in _CODE_FIELDS:
                    if type(value) is str and len(value) > _MAX_CODE_CHARS:
                        self._counters["truncated_count"] += 1
                        return
                    if not _is_code(value):
                        raise ValueError("Invalid input trace code")
                    values[key] = value
                elif type(value) is int and 0 <= value <= _MAX_INTEGER:
                    values[key] = value
                else:
                    raise ValueError("Invalid input trace number")
            data = {"trace_sequence": sequence, "recorded_time_ns": now, "stage": stage, **values}
            size = _object_size(data)
            if size > self.policy.max_record_bytes or size + 2 > self.policy.max_bytes:
                self._counters["truncated_count"] += 1
                return
            while self._records and (
                len(self._records) >= self.policy.max_records
                or self._record_bytes + size + 2 > self.policy.max_bytes
            ):
                self._record_bytes -= self._records.popleft().size_bytes + 1
                self._counters["evicted_count"] += 1
            self._records.append(_TraceRecord(sequence, now, stage, tuple(values.items()), size))
            self._record_bytes += size + 1
            self._counters["recorded_count"] += 1
        except Exception:
            self._counters["invalid_count"] += 1
        finally:
            self._lock.release()

    def _snapshot(self, now: int, reason: str | None = None) -> InputTraceSnapshot:
        self._counters["contention_count"] = next(self._contentions) - self._contention_samples
        self._contention_samples += 1
        return InputTraceSnapshot(
            captured_time_ns=now,
            records=tuple(self._records),
            counters=tuple(self._counters.items()),
            next_trace_sequence=self._next_sequence,
            retained_bytes=self._record_bytes + 2 - bool(self._records),
            reason=reason,
        )

    def snapshot(self) -> InputTraceSnapshot:
        with self._lock:
            now = self._now()
            self._expire(now)
            current = self._snapshot(now)
            return InputTraceSnapshot(
                captured_time_ns=current.captured_time_ns,
                records=current.records,
                counters=current.counters,
                next_trace_sequence=current.next_trace_sequence,
                retained_bytes=current.retained_bytes,
                frozen=tuple(item.snapshot for item in self._frozen),
                frozen_bytes=self._frozen_bytes,
            )

    def freeze(self, reason: str) -> InputTraceSnapshot | None:
        if not self._lock.acquire(blocking=False):
            next(self._contentions)
            return None
        try:
            now = self._now()
            self._expire(now)
            if not _is_code(reason):
                self._counters["invalid_count"] += 1
                return None
            if not self.policy.max_frozen:
                self._counters["frozen_dropped_count"] += 1
                return None
            # Frozen evidence never includes older frozen snapshots.
            snapshot = self._snapshot(now, reason)
            size = snapshot._size_bytes()
            if size > self.policy.max_frozen_bytes:
                self._counters["frozen_dropped_count"] += 1
                return None
            while self._frozen and (
                len(self._frozen) >= self.policy.max_frozen
                or self._frozen_bytes + size > self.policy.max_frozen_bytes
            ):
                self._frozen_bytes -= self._frozen.popleft().size_bytes
                self._counters["frozen_evicted_count"] += 1
            self._frozen.append(_FrozenTrace(snapshot, size))
            self._frozen_bytes += size
            self._counters["frozen_count"] += 1
            return snapshot
        except Exception:
            self._counters["invalid_count"] += 1
            return None
        finally:
            self._lock.release()
