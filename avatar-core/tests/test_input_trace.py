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

from alphaavatar.core.log.trace import InputTrace, InputTracePolicy


class ManualClock:
    def __init__(self) -> None:
        self.seconds = 100.0

    def __call__(self) -> float:
        return self.seconds


def compact_size(value: object) -> int:
    return len(json.dumps(value, separators=(",", ":")))


def test_identities_are_salted_hashes_joined_across_stages() -> None:
    trace = InputTrace()
    trace.record("segment.final", segment_id="private-segment", text_chars=5)
    trace.record("turn.cutoff", segment_id="private-segment", cutoff_sequence=3)
    records = trace.snapshot().to_dict()["records"]
    assert "private-segment" not in json.dumps(records)
    assert records[0]["segment_id"] == records[1]["segment_id"]

    other = InputTrace()
    other.record("segment.final", segment_id="private-segment")
    assert other.snapshot().to_dict()["records"][0]["segment_id"] != records[0]["segment_id"]


def test_invalid_records_are_counted_without_raising_or_retaining_content() -> None:
    trace = InputTrace()
    trace.record("turn.commit", transcript="raw user text")
    trace.record("Not A Code", turn_id="turn")
    trace.record("turn.commit", outcome="Has Spaces")
    snapshot = trace.snapshot()
    assert snapshot.records == ()
    assert dict(snapshot.counters)["invalid_count"] == 3


def test_retention_is_bounded_by_count_and_ttl_with_compact_byte_accounting() -> None:
    clock = ManualClock()
    trace = InputTrace(InputTracePolicy(max_records=3, ttl_sec=10.0), clock=clock)
    for sequence in range(5):
        trace.record("frame.received", sequence=sequence)
    snapshot = trace.snapshot()
    assert [record.to_dict()["sequence"] for record in snapshot.records] == [2, 3, 4]
    assert dict(snapshot.counters)["evicted_count"] == 2
    assert snapshot.retained_bytes == compact_size(snapshot.to_dict()["records"])

    clock.seconds += 10.0
    expired = trace.snapshot()
    assert expired.records == ()
    assert dict(expired.counters)["expired_count"] == 3


def test_frozen_snapshots_are_bounded_and_never_nest() -> None:
    trace = InputTrace(InputTracePolicy(max_frozen=1))
    trace.record("turn.cutoff", cutoff_sequence=1)
    first = trace.freeze("turn_timeout")
    second = trace.freeze("turn_timeout")
    assert first is not None and second is not None and second.frozen == ()

    snapshot = trace.snapshot()
    assert len(snapshot.frozen) == 1
    assert dict(snapshot.counters)["frozen_evicted_count"] == 1
    assert snapshot.frozen_bytes == compact_size(second.to_dict())
