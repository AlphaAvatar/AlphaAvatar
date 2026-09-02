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

from alphaavatar.agents.interaction import (
    InvocationDetectorBase,
    InvocationPhrase,
)
from alphaavatar.agents.runtime.inference import InferenceExecutor

from .sherpa import SherpaInvocationDetector


def create_invocation_detector(
    provider: str,
    *,
    inference_executor: InferenceExecutor,
    phrases: tuple[InvocationPhrase, ...],
    chunk_duration_ms: int,
    max_pending_chunks: int,
    tail_padding_sec: float,
) -> InvocationDetectorBase:
    if provider == "sherpa_onnx":
        return SherpaInvocationDetector(
            inference_executor=inference_executor,
            phrases=phrases,
            chunk_duration_ms=chunk_duration_ms,
            max_pending_chunks=max_pending_chunks,
            tail_padding_sec=tail_padding_sec,
        )

    raise ValueError(f"Unsupported invocation detector provider: {provider!r}")
