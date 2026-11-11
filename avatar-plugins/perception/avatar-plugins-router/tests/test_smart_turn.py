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
"""Smart Turn v3 over a temporal input window, with an offline runner: the sound it hears on
the window's media time, and one inference per sound for every assessment that needs it."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from alphaavatar.agents.router.enums import AssessmentLabel, TurnTakingMode
from alphaavatar.agents.router.schemas import TurnTakingAudioEvidence, TurnTakingEvidence
from alphaavatar.core.env.schemas import PerceptionSegmentRef, PerceptionSourceRef
from alphaavatar.core.time import RuntimeTime, RuntimeTimeRange
from alphaavatar.plugins.router.processors.turn_taking.config import TurnTakingModelConfig
from alphaavatar.plugins.router.processors.turn_taking.models.model_files import (
    SMART_TURN_V3_CONFIG,
)
from alphaavatar.plugins.router.processors.turn_taking.models.smart_turn_v3 import SmartTurnV3Model
from alphaavatar.plugins.router.processors.turn_taking.runner import SmartTurnV3Runner

HANG_GUARD = 10
RATE = SMART_TURN_V3_CONFIG.sample_rate
ORIGIN = 1_000_000_000_000
NEAR, FAR = PerceptionSourceRef("speech:near", 1), PerceptionSourceRef("speech:far", 1)
MIRROR = PerceptionSourceRef("speech:mirror", 1)


class Runner:
    """The inference service: each sound it is asked about, then ``probability`` once ``gate``
    is set. Cancelled while answering, it takes until ``released`` to stop."""

    def __init__(self, probability: float = 0.8) -> None:
        self.probability, self.heard = probability, []
        self.gate, self.released = asyncio.Event(), asyncio.Event()
        self.gate.set()
        self.released.set()

    async def do_inference(self, method: str, data: bytes) -> bytes:
        assert method == SmartTurnV3Runner.INFERENCE_METHOD
        self.heard.append(np.frombuffer(data, dtype="<i2"))
        try:
            await self.gate.wait()
        except asyncio.CancelledError:
            await self.released.wait()
            raise
        return np.float32(self.probability).tobytes()


def smart_turn(runner: Runner, **thresholds: float) -> SmartTurnV3Model:
    """Smart Turn with its configured thresholds, unless ``thresholds`` replace them."""
    config = TurnTakingModelConfig(**thresholds)
    return SmartTurnV3Model(
        inference_executor=runner,
        incomplete_threshold=config.incomplete_threshold,
        complete_threshold=config.complete_threshold,
    )


def at(seconds: float) -> RuntimeTime:
    ns = ORIGIN + round(seconds * 1e9)
    return RuntimeTime(ns, ns)


def sound(source: PerceptionSourceRef, segment: str, start: float, pcm: np.ndarray):
    """A segment of ``pcm`` from ``start`` seconds, on the window's media clock."""
    return TurnTakingAudioEvidence(
        segment=PerceptionSegmentRef(source, segment),
        time_range=RuntimeTimeRange(at(start), at(start + len(pcm) / RATE)),
        pcm16_bytes=pcm.astype("<i2").tobytes(),
        sample_rate=RATE,
        num_channels=1,
        samples_per_channel=len(pcm),
    )


def tone(value: int, seconds: float) -> np.ndarray:
    return np.full(round(seconds * RATE), value, dtype="<i2")


def window(*audio: TurnTakingAudioEvidence, input_id: str = "input", revision: int = 1):
    return TurnTakingEvidence(
        input_id=input_id,
        revision=revision,
        turn_mode=TurnTakingMode.AUDIO_ONLY,
        started_at=audio[0].time_range.start,
        updated_at=audio[-1].time_range.end,
        segments=tuple(item.segment for item in audio),
        input_observation_ids=(),
        audio=audio,
    )


A, B, C = tone(1000, 0.5), tone(3000, 0.5), tone(4000, 0.5)
HEARD = {
    # Silence between a source's segments is the time that passed, not left out.
    "pause": (
        (sound(NEAR, "a", 0.0, A), sound(NEAR, "b", 0.75, B)),
        np.concatenate([A, tone(0, 0.25), B]),
    ),
    # Two sources heard at once are averaged where they overlap.
    "overlap": (
        (sound(NEAR, "a", 0.0, A), sound(FAR, "c", 0.25, C)),
        np.concatenate([tone(1000, 0.25), tone(2500, 0.25), tone(4000, 0.25)]),
    ),
    # A mirrored track, the same sound at the same time from another source, counts once.
    "mirror": (
        (sound(NEAR, "a", 0.0, A), sound(MIRROR, "m", 0.0, A), sound(FAR, "c", 0.0, C)),
        tone(2500, 0.5),
    ),
    # A source's overlapping segments carry the same samples: their overlap plays once.
    "one-source-overlap": (
        (sound(NEAR, "a", 0.0, A), sound(NEAR, "b", 0.25, B)),
        np.concatenate([tone(1000, 0.25), B]),
    ),
    # An hour apart, only the model's last seconds are built: the earlier sound falls outside.
    "an-hour-apart": (
        (sound(NEAR, "a", 0.0, A), sound(NEAR, "b", 3600.0, B)),
        np.concatenate([tone(0, SMART_TURN_V3_CONFIG.max_audio_sec - 0.5), B]),
    ),
}


@pytest.mark.parametrize("case", HEARD)
async def test_the_window_is_heard_on_its_media_time_its_sources_mixed_and_mirrors_once(
    case: str,
) -> None:
    runner = Runner()
    model = smart_turn(runner)
    audio, expected = HEARD[case]
    assessment = await model.assess(window(*audio))

    (heard,) = runner.heard
    np.testing.assert_array_equal(heard, expected)
    assert assessment.speech_completion == AssessmentLabel.POSITIVE
    assert assessment.speech_completion_probability == pytest.approx(0.8)


@pytest.mark.parametrize(
    ("probability", "label"),
    [
        (0.2, AssessmentLabel.NEGATIVE),
        (0.5, AssessmentLabel.UNKNOWN),
        (0.9, AssessmentLabel.POSITIVE),
    ],
    ids=["incomplete", "uncertain", "complete"],
)
async def test_the_probability_is_a_clear_judgment_only_beyond_its_thresholds(
    probability: float, label: AssessmentLabel
) -> None:
    # Between the thresholds the model abstains: only a deadline settles that uncertainty.
    assessment = await smart_turn(Runner(probability)).assess(window(sound(NEAR, "a", 0.0, A)))
    assert assessment.speech_completion == label
    assert assessment.speech_completion_probability == pytest.approx(probability)
    with pytest.raises(ValueError, match="incomplete"):
        smart_turn(Runner(), incomplete_threshold=0.7, complete_threshold=0.3)


async def test_one_inference_answers_each_assessment_of_the_same_sound_for_its_own_input() -> None:
    runner = Runner(probability=0.25)
    runner.gate.clear()
    model = smart_turn(runner)
    audio = (sound(NEAR, "a", 0.0, A),)
    first = asyncio.create_task(model.assess(window(*audio, input_id="first", revision=1)))
    second = asyncio.create_task(model.assess(window(*audio, input_id="second", revision=3)))
    await asyncio.sleep(0.01)
    runner.gate.set()
    answers = await asyncio.wait_for(asyncio.gather(first, second), HANG_GUARD)
    # Reused again once answered, and a different sound asks again.
    again = await model.assess(window(*audio, input_id="first", revision=2))
    other = await model.assess(window(sound(NEAR, "b", 0.0, B), input_id="first", revision=4))

    assert len(runner.heard) == 2
    assert [(a.input_id, a.revision) for a in (*answers, again, other)] == [
        ("first", 1),
        ("second", 3),
        ("first", 2),
        ("first", 4),
    ]
    assert {
        (a.speech_completion, a.speech_completion_probability) for a in (*answers, again, other)
    } == {(AssessmentLabel.NEGATIVE, 0.25)}


async def test_a_cancelled_assessment_leaves_its_inference_to_answer_the_next() -> None:
    runner = Runner()
    runner.gate.clear()
    model = smart_turn(runner)
    audio = (sound(NEAR, "a", 0.0, A),)
    cancelled = asyncio.create_task(model.assess(window(*audio, revision=1)))
    await asyncio.sleep(0.01)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled

    later = asyncio.create_task(model.assess(window(*audio, revision=2)))
    await asyncio.sleep(0.01)
    runner.gate.set()
    assessment = await asyncio.wait_for(later, HANG_GUARD)
    assert len(runner.heard) == 1 and assessment.revision == 2


async def test_closing_cancels_its_inference_refuses_assessments_and_forgets_what_it_heard() -> (
    None
):
    runner = Runner()
    model = smart_turn(runner)
    heard, pending = (sound(NEAR, "a", 0.0, A),), (sound(NEAR, "b", 0.0, B),)
    await model.assess(window(*heard))
    runner.gate.clear()
    runner.released.clear()
    asking = asyncio.create_task(model.assess(window(*pending)))
    await asyncio.sleep(0.01)
    closing = asyncio.create_task(model.aclose())
    await asyncio.sleep(0.01)
    # While its inference stops, the model takes no assessment and keeps closing.
    with pytest.raises(RuntimeError, match="closing"):
        await asyncio.wait_for(model.assess(window(*heard)), HANG_GUARD)
    assert not closing.done()

    runner.released.set()
    await asyncio.wait_for(closing, HANG_GUARD)
    with pytest.raises(asyncio.CancelledError):
        await asking
    # Closed, it keeps nothing: a sound it had answered is heard again.
    runner.gate.set()
    await model.assess(window(*heard))
    assert len(runner.heard) == 3
