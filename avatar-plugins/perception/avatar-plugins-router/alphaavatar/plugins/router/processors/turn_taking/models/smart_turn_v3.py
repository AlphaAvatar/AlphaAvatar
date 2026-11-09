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

import asyncio
import hashlib
from itertools import groupby

import numpy as np

from alphaavatar.agents.router.enums import AddressingMode, AssessmentLabel, TurnTakingMode
from alphaavatar.agents.router.models import TurnTakingModelBase, TurnTakingModelCapabilities
from alphaavatar.agents.router.schemas import (
    TurnTakingAssessment,
    TurnTakingAudioEvidence,
    TurnTakingEvidence,
)
from alphaavatar.agents.runtime.inference import InferenceExecutor
from alphaavatar.core.cleanup import wait_for_cleanup

from ..runner import SmartTurnV3Runner
from .model_files import SMART_TURN_V3_CONFIG


class SmartTurnV3Model(TurnTakingModelBase):
    def __init__(
        self,
        *,
        inference_executor: InferenceExecutor,
        incomplete_threshold: float,
        complete_threshold: float,
    ) -> None:
        if not 0.0 <= incomplete_threshold < complete_threshold <= 1.0:
            raise ValueError("Smart Turn thresholds must satisfy 0 <= incomplete < complete <= 1")

        self._executor = inference_executor
        self._incomplete_threshold = incomplete_threshold
        self._complete_threshold = complete_threshold

        self._inflight: tuple[bytes, asyncio.Task[float]] | None = None
        self._cached: tuple[bytes, float] | None = None
        self._closing = False
        self._close_task: asyncio.Task[None] | None = None

    @property
    def name(self) -> str:
        return "smart_turn_v3"

    @property
    def capabilities(self) -> TurnTakingModelCapabilities:
        return TurnTakingModelCapabilities(
            modes=frozenset({TurnTakingMode.AUDIO_ONLY, TurnTakingMode.AUDIO_VISUAL}),
            uses_audio=True,
            uses_transcript=False,
            uses_annotations=False,
        )

    @staticmethod
    def _build_pcm(evidence: TurnTakingEvidence) -> bytes:
        config = SMART_TURN_V3_CONFIG
        audio = evidence.audio
        if not audio:
            return b""

        for item in audio:
            if item.sample_rate != config.sample_rate:
                raise ValueError(
                    f"Smart Turn requires {config.sample_rate} Hz audio, got {item.sample_rate}"
                )
            if item.num_channels != config.num_channels:
                raise ValueError(
                    f"Smart Turn requires {config.num_channels} channel audio, "
                    f"got {item.num_channels}"
                )

        end_ns = max(item.time_range.end.monotonic_ns for item in audio)
        start_ns = max(
            min(item.time_range.start.monotonic_ns for item in audio),
            end_ns - round(config.max_audio_sec * 1_000_000_000),
        )
        samples = min(
            config.max_samples, round((end_ns - start_ns) * config.sample_rate / 1_000_000_000)
        )
        if samples <= 0:
            return b""

        # Allocate only the selected tail, even when two observations are hours apart.
        # Sources overlap in media time; concatenating their recordings would invent time.
        mixed = np.zeros(samples, dtype=np.float64)
        contributors = np.zeros(samples, dtype=np.int64)
        seen: set[bytes] = set()

        def source_key(item: TurnTakingAudioEvidence) -> tuple[str, int]:
            source = item.segment.source
            return source.source_id, source.source_generation

        ordered = sorted(
            audio,
            key=lambda item: (
                *source_key(item),
                item.time_range.start.monotonic_ns,
                item.time_range.end.monotonic_ns,
                item.segment.segment_id,
            ),
        )
        for _, items in groupby(ordered, key=source_key):
            track = np.zeros(samples, dtype="<i2")
            present = np.zeros(samples, dtype=np.bool_)
            for item in items:
                if item.time_range.end.monotonic_ns <= start_ns:
                    continue
                offset = round(
                    (item.time_range.start.monotonic_ns - start_ns)
                    * config.sample_rate
                    / 1_000_000_000
                )
                first = max(0, offset)
                source_first = max(0, -offset)
                last = min(
                    samples,
                    round(
                        (item.time_range.end.monotonic_ns - start_ns)
                        * config.sample_rate
                        / 1_000_000_000
                    ),
                    offset + item.samples_per_channel,
                )
                if last <= first:
                    continue
                # Overlapping segments from one source carry the same media samples. The
                # later segment replaces their overlap, rather than playing it twice.
                track[first:last] = np.frombuffer(
                    item.pcm16_bytes, dtype="<i2", count=last - first, offset=source_first * 2
                )
                present[first:last] = True
            if not present.any():
                continue
            # Mirrored tracks with identical, aligned PCM contribute only once. Entity
            # labels do not select or exclude audio from the temporal input window.
            digest = hashlib.blake2b(digest_size=32)
            digest.update(track)
            digest.update(present)
            key = digest.digest()
            if key in seen:
                continue
            seen.add(key)
            mixed += track
            contributors += present

        # Average the sources present at each sample to keep simultaneous audio bounded.
        mixed /= np.maximum(contributors, 1)
        return np.clip(np.rint(mixed), -32768, 32767).astype("<i2").tobytes()

    async def _run_inference(self, pcm16_bytes: bytes) -> float:
        try:
            result = await self._executor.do_inference(
                SmartTurnV3Runner.INFERENCE_METHOD, pcm16_bytes
            )
            if result is None:
                raise RuntimeError("Smart Turn runner returned no inference result")
            values = np.frombuffer(result, dtype=np.float32)
            if values.size != 1 or not np.isfinite(values[0]):
                raise RuntimeError("Smart Turn runner must return one finite probability")
            probability = float(np.clip(values[0], 0.0, 1.0))
            if not self._closing:
                self._cached = pcm16_bytes, probability
            return probability
        finally:
            if self._inflight is not None and self._inflight[1] is asyncio.current_task():
                self._inflight = None

    async def _infer(self, pcm16_bytes: bytes) -> float:
        while True:
            if self._closing:
                raise RuntimeError("Smart Turn model is closing")
            if self._cached is not None and self._cached[0] == pcm16_bytes:
                return self._cached[1]
            if self._inflight is None:
                task = asyncio.create_task(
                    self._run_inference(pcm16_bytes), name="smart_turn_v3_inference"
                )
                self._inflight = pcm16_bytes, task
                # A cancelled assessment may leave no waiter to retrieve a runner failure.
                task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
            previous_pcm, task = self._inflight
            if previous_pcm == pcm16_bytes:
                # Assessment cancellation must not break the runtime's inference connection.
                return await asyncio.shield(task)
            try:
                await asyncio.shield(task)
            except Exception:
                # A different window does not inherit the previous window's failure.
                pass

    async def assess(self, evidence: TurnTakingEvidence) -> TurnTakingAssessment:
        if not self.capabilities.supports(evidence.turn_mode):
            raise ValueError(f"Smart Turn does not support mode={evidence.turn_mode.value}")

        pcm16_bytes = self._build_pcm(evidence)
        if not pcm16_bytes:
            return TurnTakingAssessment(
                input_id=evidence.input_id,
                revision=evidence.revision,
                turn_mode=evidence.turn_mode,
                confidence=0.0,
                speech_completion=AssessmentLabel.UNKNOWN,
                speech_completion_probability=None,
                addressing_mode=AddressingMode.UNKNOWN,
                reason="smart_turn_missing_audio",
            )

        probability = await self._infer(pcm16_bytes)
        if probability <= self._incomplete_threshold:
            completion = AssessmentLabel.NEGATIVE
        elif probability >= self._complete_threshold:
            completion = AssessmentLabel.POSITIVE
        else:
            completion = AssessmentLabel.UNKNOWN

        return TurnTakingAssessment(
            input_id=evidence.input_id,
            revision=evidence.revision,
            turn_mode=evidence.turn_mode,
            confidence=max(probability, 1.0 - probability),
            speech_completion=completion,
            speech_completion_probability=probability,
            addressing_mode=AddressingMode.UNKNOWN,
            reason="smart_turn_v3.2",
        )

    async def _close(self) -> None:
        self._cached = None
        if self._inflight is not None:
            task = self._inflight[1]
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def aclose(self) -> None:
        if self._close_task is None:
            self._closing = True
            self._close_task = asyncio.create_task(self._close(), name="smart_turn_v3_close")
        task = self._close_task
        try:
            await wait_for_cleanup(task)
        finally:
            if task.done() and self._close_task is task:
                self._close_task = None
                self._closing = False
