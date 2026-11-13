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
"""A segment's speaker association settles once, however it is released, and the trace says
when and how, recognized or not."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from alphaavatar.agents.runtime.modules.participants import ParticipantRuntime
from alphaavatar.agents.workspace import WorkspacePaths
from alphaavatar.core.env.schemas import (
    PerceptionEntityRef,
    PerceptionSegmentRef,
    PerceptionSourceRef,
)
from alphaavatar.core.perception import PerceptionRuntime
from alphaavatar.core.perception.enums import PerceptionStreamKind
from alphaavatar.core.session import SessionRuntime
from alphaavatar.core.turn import TurnRuntime

SOURCE = PerceptionSourceRef("microphone", 1)
VOICE = PerceptionEntityRef("voice-alice")


def participants(tmp_path: Path, **limits: int) -> ParticipantRuntime:
    session = SessionRuntime(session_id="session-1")
    perception = PerceptionRuntime(
        session_id="session-1",
        stream_maxlens=dict.fromkeys(PerceptionStreamKind, 64),
        clock=session.clock,
    )
    return ParticipantRuntime(
        session=session,
        workspace=WorkspacePaths.from_root(tmp_path / "workspace"),
        turn=TurnRuntime(perception=perception),
        **limits,
    )


def ready(runtime: ParticipantRuntime) -> list[dict]:
    records = runtime.turn.perception.input_trace.snapshot().to_dict()["records"]
    return [r for r in records if r["stage"] == "participant.segment_ready"]


def bound(runtime: ParticipantRuntime, segment: PerceptionSegmentRef, token: int) -> None:
    runtime.ensure_entity(SOURCE, VOICE, kind="speaker", device_id="microphone")
    assert runtime.bind_segment(segment, VOICE, token=token)


@pytest.mark.parametrize(
    ("release", "outcome", "reason"),
    [
        (bound, "bound", None),
        (lambda r, s, t: r.finish_segment_resolution(s, token=t), "unbound", None),
        (lambda r, s, t: r.bind_segment(s, None, token=t), "invalid", "no_entity"),
        (lambda r, s, t: r.invalidate_segment(s), "invalid", "invalidated"),
        (lambda r, s, t: r.retire_source(SOURCE), "released", "source_retired"),
        (lambda r, s, t: r.close(), "released", "closed"),
    ],
    ids=["bound", "unbound", "no-entity", "invalidated", "retired", "closed"],
)
def test_an_association_settles_once_and_the_trace_says_how(
    release: Callable, outcome: str, reason: str | None, tmp_path: Path
) -> None:
    runtime = participants(tmp_path)
    segment = PerceptionSegmentRef(SOURCE, "seg-1")
    token = runtime.observe_segment(segment)
    assert ready(runtime) == []  # Asked for, not ready yet.
    release(runtime, segment, token)
    # Released, whatever released it; and settled once: what follows changes no readiness.
    runtime.finish_segment_resolution(segment, token=token)
    runtime.invalidate_segment(segment)
    (record,) = ready(runtime)
    assert (record["outcome"], record.get("reason")) == (outcome, reason)
    assert record["start_time_ns"] <= record["end_time_ns"]


def test_past_the_bound_an_association_is_released(tmp_path: Path) -> None:
    runtime = participants(tmp_path, max_segments=1)
    runtime.observe_segment(PerceptionSegmentRef(SOURCE, "seg-1"))
    runtime.observe_segment(PerceptionSegmentRef(SOURCE, "seg-2"))  # Evicts seg-1
    assert [(r["outcome"], r["reason"]) for r in ready(runtime)] == [("released", "evicted")]
