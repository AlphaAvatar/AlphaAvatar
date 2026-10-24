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
import logging
import math
import os
from time import perf_counter

import llama_cpp

from alphaavatar.agents.router.enums import SemanticAddressingLabel
from alphaavatar.agents.router.schemas import SemanticAddressingRequest, SemanticAddressingResult
from alphaavatar.agents.runtime.inference import InferenceRunner
from alphaavatar.agents.runtime.inference.cpu import available_cpu_count

from .model_files import SEMANTIC_ADDRESSING_CONFIG, resolve_semantic_addressing_files
from .prompt import SemanticAddressingPrompt

logger = logging.getLogger(__name__)


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
        started = perf_counter()
        tokens = self._tokenize(prompt)
        tokenized = perf_counter()
        if not tokens or len(tokens) > SEMANTIC_ADDRESSING_CONFIG.context_length:
            raise ValueError(
                f"Semantic Addressing token count outside 1.."
                f"{SEMANTIC_ADDRESSING_CONFIG.context_length}: {len(tokens)}"
            )

        # Token boundaries can change at the template suffix. Reuse only the actual live prefix.
        cached = 0
        limit = min(len(tokens) - 1, len(self._cached_tokens), self._llm.n_tokens)
        while cached < limit and tokens[cached] == self._cached_tokens[cached]:
            cached += 1
        try:
            if cached and not self._llm._ctx.kv_cache_seq_rm(-1, cached, -1):
                cached = 0
            if cached:
                self._llm.n_tokens = cached
            else:
                self._llm.reset()
            logger.debug(
                "SEMANTIC CACHE method=%s pid=%s call=%d reused_tokens=%d previous_tokens=%d",
                self.INFERENCE_METHOD,
                os.getpid(),
                self._call_index,
                cached,
                len(self._cached_tokens),
            )
            # Always evaluate at least the final token: the last live logits must be fresh.
            logger.debug(
                "SEMANTIC PREFILL method=%s pid=%s call=%d prompt_tokens=%d cached_tokens=%d "
                "eval_tokens=%d threads=%d cpu_capacity=%.2f tokenize_ms=%.1f",
                self.INFERENCE_METHOD,
                os.getpid(),
                self._call_index,
                len(tokens),
                cached,
                len(tokens) - cached,
                self._threads,
                self._cpu_capacity,
                (tokenized - started) * 1000,
            )
            self._llm.eval(tokens[cached:])
            logits = llama_cpp.llama_get_logits_ith(self._llm.ctx, -1)
            config = SEMANTIC_ADDRESSING_CONFIG
            result = float(logits[config.label_0_token_id]), float(logits[config.label_1_token_id])
            self._cached_tokens = tokens
        except Exception:
            # A partial native eval may have advanced KV; the next request must rebuild it.
            self._cached_tokens = []
            raise
        logger.debug(
            "SEMANTIC INFERENCE COMPLETE method=%s pid=%s call=%d prefill_ms=%.1f total_ms=%.1f",
            self.INFERENCE_METHOD,
            os.getpid(),
            self._call_index,
            (perf_counter() - tokenized) * 1000,
            (perf_counter() - started) * 1000,
        )
        return result

    def initialize(self) -> None:
        requested = int(os.getenv("ALPHAAVATAR_SEMANTIC_ADDRESSING_THREADS", "0"))
        if requested < 0:
            raise ValueError("Semantic Addressing threads must be nonnegative")
        self._cpu_capacity = available_cpu_count()
        capacity = max(1, math.floor(self._cpu_capacity))
        threads = min(requested, capacity) if requested else min(8, max(1, capacity // 2))
        self._call_index, self._threads, self._cached_tokens = 0, threads, []
        started = perf_counter()
        logger.debug(
            "SEMANTIC RUNNER INITIALIZE method=%s pid=%s cpu_capacity=%.2f "
            "requested_threads=%d threads=%d",
            self.INFERENCE_METHOD,
            os.getpid(),
            self._cpu_capacity,
            requested,
            threads,
        )
        model_path, prompt_path = resolve_semantic_addressing_files()
        config = SEMANTIC_ADDRESSING_CONFIG
        self._prompt = SemanticAddressingPrompt(prompt_path)
        logger.debug(
            "SEMANTIC MODEL LOAD START method=%s pid=%s", self.INFERENCE_METHOD, os.getpid()
        )
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
        prefix = self._tokenize(self._prompt.constant_prefix)
        if not prefix or len(prefix) > config.context_length:
            raise RuntimeError("Semantic Addressing constant prefix is empty or exceeds context")
        self._validate_label_tokens()
        logger.debug(
            "SEMANTIC WARMUP START method=%s pid=%s prefix_tokens=%d load_ms=%.1f",
            self.INFERENCE_METHOD,
            os.getpid(),
            len(prefix),
            (perf_counter() - started) * 1000,
        )
        self._llm.eval(prefix)
        self._cached_tokens = prefix
        logger.debug(
            "SEMANTIC RUNNER READY method=%s pid=%s prefix_tokens=%d total_ms=%.1f",
            self.INFERENCE_METHOD,
            os.getpid(),
            len(prefix),
            (perf_counter() - started) * 1000,
        )

    def run(self, data: bytes) -> bytes:
        self._call_index += 1
        logger.debug(
            "SEMANTIC INFERENCE START method=%s pid=%s call=%d request_bytes=%d",
            self.INFERENCE_METHOD,
            os.getpid(),
            self._call_index,
            len(data),
        )
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
                label=label, label_0_logit=logit_0, label_1_logit=logit_1, p_avatar=p_avatar
            ).to_dict(),
            separators=(",", ":"),
        ).encode()

    def close(self) -> None:
        self._cached_tokens = []
        llm = getattr(self, "_llm", None)
        if llm is not None:
            llm.close()
            self._llm = None
