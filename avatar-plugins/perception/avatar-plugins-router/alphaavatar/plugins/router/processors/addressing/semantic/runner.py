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
import math
import os

import llama_cpp

from alphaavatar.agents.router import (
    SemanticAddressingLabel,
    SemanticAddressingRequest,
    SemanticAddressingResult,
)
from alphaavatar.agents.runtime.inference import InferenceRunner

from .model_files import SEMANTIC_ADDRESSING_CONFIG, resolve_semantic_addressing_files
from .prompt import SemanticAddressingPrompt


class SemanticAddressingQwen3Runner(InferenceRunner):
    INFERENCE_METHOD = "alphaavatar.router.addressing.semantic.qwen3_0_6b"

    def _tokenize(self, text: bytes) -> list[int]:
        return self._llm.tokenize(text, add_bos=False, special=True)

    def _validate_label_tokens(self) -> None:
        config = SEMANTIC_ADDRESSING_CONFIG
        prompt = self._prompt.render(SemanticAddressingRequest())
        base = self._tokenize(prompt)

        for text, expected in ((b"0", config.label_0_token_id), (b"1", config.label_1_token_id)):
            extended = self._tokenize(prompt + text)
            if extended[: len(base)] != base or extended[len(base) :] != [expected]:
                raise RuntimeError(
                    f"Semantic Addressing label token contract failed: "
                    f"label={text.decode()}, expected={expected}"
                )

    def _decode(self, prompt: bytes) -> tuple[float, float]:
        tokens = self._tokenize(prompt)
        if len(tokens) > SEMANTIC_ADDRESSING_CONFIG.context_length:
            raise ValueError(
                f"Semantic Addressing context too long: "
                f"{len(tokens)} > {SEMANTIC_ADDRESSING_CONFIG.context_length}"
            )

        prefix_length = self._prefix_length
        if tokens[:prefix_length] == self._prefix_tokens:
            self._llm.n_tokens = prefix_length
            self._llm.eval(tokens[prefix_length:])
        else:
            self._llm.reset()
            self._llm.eval(tokens)

        logits = llama_cpp.llama_get_logits_ith(self._llm.ctx, -1)
        config = SEMANTIC_ADDRESSING_CONFIG
        return float(logits[config.label_0_token_id]), float(logits[config.label_1_token_id])

    def initialize(self) -> None:
        model_path, prompt_path = resolve_semantic_addressing_files()
        config = SEMANTIC_ADDRESSING_CONFIG
        threads = int(os.getenv("ALPHAAVATAR_SEMANTIC_ADDRESSING_THREADS", "0"))
        threads = threads or min(8, max(1, (os.cpu_count() or 2) // 2))

        self._prompt = SemanticAddressingPrompt(prompt_path)
        self._llm = llama_cpp.Llama(
            model_path=model_path,
            n_ctx=config.context_length,
            n_batch=512,
            n_ubatch=512,
            n_threads=threads,
            n_threads_batch=threads,
            n_gpu_layers=0,
            use_mmap=True,
            logits_all=False,
            embedding=False,
            verbose=False,
        )

        self._prefix_tokens = self._tokenize(self._prompt.constant_prefix)
        if not self._prefix_tokens:
            raise RuntimeError("Semantic Addressing constant prefix is empty")

        self._validate_label_tokens()
        self._llm.eval(self._prefix_tokens)
        self._prefix_length = len(self._prefix_tokens)

    def run(self, data: bytes) -> bytes:
        request = SemanticAddressingRequest.from_dict(json.loads(data))
        logit_0, logit_1 = self._decode(self._prompt.render(request))
        p_avatar = 0.5 * (1.0 + math.tanh((logit_1 - logit_0) * 0.5))
        config = SEMANTIC_ADDRESSING_CONFIG

        if p_avatar >= config.uncertainty_high:
            label = SemanticAddressingLabel.AVATAR
        elif p_avatar <= config.uncertainty_low:
            label = SemanticAddressingLabel.NON_AVATAR
        else:
            label = SemanticAddressingLabel.UNKNOWN

        return json.dumps(
            SemanticAddressingResult(
                label=label,
                label_0_logit=logit_0,
                label_1_logit=logit_1,
                p_avatar=p_avatar,
            ).to_dict(),
            separators=(",", ":"),
        ).encode()

    def close(self) -> None:
        llm = getattr(self, "_llm", None)
        if llm is not None:
            llm.close()
            self._llm = None
