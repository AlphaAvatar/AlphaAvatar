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

import numpy as np

from alphaavatar.agents.interaction import (
    AddressingMode,
    TurnTakingAssessment,
    TurnTakingEvidence,
    TurnTakingMode,
    TurnTakingModelBase,
    TurnTakingModelCapabilities,
)
from alphaavatar.agents.runtime.inference import InferenceExecutor

from .model_files import SMART_TURN_V3_CONFIG
from .runner.smart_turn_v3 import SmartTurnV3Runner


class SmartTurnV3Model(TurnTakingModelBase):
    def __init__(self, *, inference_executor: InferenceExecutor) -> None:
        self._executor = inference_executor
        self._inflight: set[asyncio.Task[bytes | None]] = set()

    @property
    def name(self) -> str:
        return "smart_turn_v3"

    @property
    def capabilities(self) -> TurnTakingModelCapabilities:
        return TurnTakingModelCapabilities(
            modes=frozenset(
                {
                    TurnTakingMode.AUDIO_ONLY,
                    TurnTakingMode.AUDIO_VISUAL,
                }
            ),
            uses_audio=True,
            uses_transcript=False,
            uses_annotations=False,
        )

    @staticmethod
    def _build_pcm(evidence: TurnTakingEvidence) -> bytes:
        config = SMART_TURN_V3_CONFIG
        audio = sorted(
            evidence.audio,
            key=lambda item: item.time_range.start.monotonic_ns,
        )
        if not audio:
            return b""

        parts: list[bytes] = []
        previous_end_ns: int | None = None

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

            if previous_end_ns is not None:
                gap_ns = item.time_range.start.monotonic_ns - previous_end_ns
                if gap_ns > 0:
                    gap_samples = round(gap_ns * config.sample_rate / 1_000_000_000)
                    parts.append(bytes(gap_samples * 2))

            parts.append(item.pcm16_bytes)
            previous_end_ns = max(
                previous_end_ns or 0,
                item.time_range.end.monotonic_ns,
            )

        return b"".join(parts)[-(config.max_samples * 2) :]

    def _track_inference(self, task: asyncio.Task[bytes | None]) -> None:
        self._inflight.add(task)

        def done(completed: asyncio.Task[bytes | None]) -> None:
            self._inflight.discard(completed)
            if completed.cancelled():
                return

            try:
                completed.exception()
            except Exception:
                pass

        task.add_done_callback(done)

    async def _infer(self, pcm16_bytes: bytes) -> bytes | None:
        task = asyncio.create_task(
            self._executor.do_inference(
                SmartTurnV3Runner.INFERENCE_METHOD,
                pcm16_bytes,
            ),
            name="smart_turn_v3_inference",
        )
        self._track_inference(task)

        # Cancelling a TurnTaking assessment must not cancel an already-running
        # inference request and drop its runtime connection.
        return await asyncio.shield(task)

    async def assess(self, evidence: TurnTakingEvidence) -> TurnTakingAssessment:
        if not self.capabilities.supports(evidence.turn_mode):
            raise ValueError(f"Smart Turn does not support mode={evidence.turn_mode.value}")

        pcm16_bytes = self._build_pcm(evidence)
        if not pcm16_bytes:
            return TurnTakingAssessment(
                turn_candidate_id=evidence.turn_candidate_id,
                candidate_revision=evidence.candidate_revision,
                turn_mode=evidence.turn_mode,
                confidence=1.0,
                end_of_turn_probability=0.0,
                addressing_mode=AddressingMode.UNKNOWN,
                reason="smart_turn_missing_audio",
            )

        result = await self._infer(pcm16_bytes)
        if result is None:
            raise RuntimeError("Smart Turn runner returned no inference result")

        values = np.frombuffer(result, dtype=np.float32)
        if values.size != 1:
            raise RuntimeError(f"Invalid Smart Turn response size: values={values.size}")

        probability = float(np.clip(values[0], 0.0, 1.0))

        return TurnTakingAssessment(
            turn_candidate_id=evidence.turn_candidate_id,
            candidate_revision=evidence.candidate_revision,
            turn_mode=evidence.turn_mode,
            confidence=max(probability, 1.0 - probability),
            end_of_turn_probability=probability,
            addressing_mode=AddressingMode.UNKNOWN,
            reason="smart_turn_v3.2",
        )
