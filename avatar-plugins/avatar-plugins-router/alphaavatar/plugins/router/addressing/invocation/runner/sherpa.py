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

import re
from typing import Any

import numpy as np

from alphaavatar.agents.runtime.inference import InferenceRunner

from ..model_files import resolve_sherpa_kws_model_dir
from ..wire import InvocationRunnerOperation, decode_packet, encode_response

_CJK_WORD = re.compile(r"^[\u4e00-\u9fff]+$")


def _normalize_phrase(text: str) -> str:
    return " ".join(
        word if _CJK_WORD.fullmatch(word) else word.upper() for word in text.strip().split()
    )


class SherpaKeywordSpotterRunner(InferenceRunner):
    INFERENCE_METHOD = "alphaavatar.router.addressing.invocation.sherpa"

    @staticmethod
    def _samples(data: bytes, *, num_channels: int) -> np.ndarray:
        if num_channels <= 0:
            raise ValueError("num_channels must be positive")
        if not data:
            return np.empty(0, dtype=np.float32)
        if len(data) % (num_channels * 2):
            raise ValueError("PCM16 request size does not match channel count")

        samples = np.frombuffer(data, dtype="<i2").reshape(-1, num_channels)
        mono = (
            samples[:, 0].astype(np.float32)
            if num_channels == 1
            else samples.astype(np.float32).mean(axis=1)
        )
        return mono / 32768.0

    @staticmethod
    def _decode(spotter, stream) -> tuple[str, ...]:
        labels: list[str] = []

        while spotter.is_ready(stream):
            spotter.decode_stream(stream)
            label = spotter.get_result(stream)

            if label:
                labels.append(label)
                spotter.reset_stream(stream)

        return tuple(dict.fromkeys(labels))

    def _compile_profile(self, profile: dict[str, Any]) -> str:
        profile_id = str(profile["profile_id"])
        cached = self._profiles.get(profile_id)
        if cached is not None:
            return cached

        lines: list[str] = []

        for phrase in profile.get("phrases", ()):
            phrase_id = str(phrase["phrase_id"])
            text = _normalize_phrase(str(phrase["text"]))
            encoded = self._sherpa.text2token(
                [text],
                tokens=self._tokens,
                tokens_type="phone+ppinyin",
                lexicon=self._lexicon,
            )

            if len(encoded) != 1 or not encoded[0]:
                raise ValueError(
                    f"Invocation phrase cannot be tokenized: phrase_id={phrase_id!r}, text={text!r}"
                )

            lines.append(
                f"{' '.join(str(token) for token in encoded[0])} "
                f":{float(phrase['boosting_score']):g} "
                f"#{float(phrase['trigger_threshold']):g} "
                f"@{phrase_id}"
            )

        if not lines:
            raise ValueError("Invocation keyword profile cannot be empty")

        compiled = "\n".join(lines)
        self._profiles[profile_id] = compiled
        return compiled

    def _keywords_file(self, profile: dict[str, Any]) -> str:
        profile_id = str(profile["profile_id"])
        compiled = self._compile_profile(profile)

        directory = self._model_dir / ".alphaavatar" / "invocation_profiles"
        directory.mkdir(parents=True, exist_ok=True)

        path = directory / f"{profile_id}.txt"
        if not path.is_file() or path.read_text(encoding="utf-8") != compiled:
            temporary = path.with_suffix(".tmp")
            temporary.write_text(compiled, encoding="utf-8")
            temporary.replace(path)

        return str(path)

    def _spotter(self, profile: dict[str, Any]):
        profile_id = str(profile["profile_id"])
        spotter = self._spotters.get(profile_id)
        if spotter is not None:
            return spotter

        model_dir = self._model_dir
        spotter = self._sherpa.KeywordSpotter(
            tokens=self._tokens,
            encoder=str(model_dir / "encoder-epoch-13-avg-2-chunk-8-left-64.int8.onnx"),
            decoder=str(model_dir / "decoder-epoch-13-avg-2-chunk-8-left-64.onnx"),
            joiner=str(model_dir / "joiner-epoch-13-avg-2-chunk-8-left-64.int8.onnx"),
            keywords_file=self._keywords_file(profile),
            num_threads=2,
            provider="cpu",
        )

        self._spotters[profile_id] = spotter
        return spotter

    def _stream(self, *, stream_id: str, profile: dict[str, Any]):
        profile_id = str(profile["profile_id"])
        key = profile_id, stream_id

        spotter = self._spotter(profile)
        stream = self._streams.get(key)

        if stream is None:
            stream = spotter.create_stream()
            self._streams[key] = stream

        return spotter, stream

    def _warmup(self, profile: dict[str, Any]) -> None:
        profile_id = str(profile["profile_id"])
        if profile_id in self._warmed_profiles:
            return

        spotter = self._spotter(profile)
        stream = spotter.create_stream()

        sample_rate = 16_000
        stream.accept_waveform(
            sample_rate,
            np.zeros(sample_rate, dtype=np.float32),
        )
        stream.input_finished()
        self._decode(spotter, stream)

        self._warmed_profiles.add(profile_id)

    def initialize(self) -> None:
        import sherpa_onnx

        model_dir = resolve_sherpa_kws_model_dir(local_files_only=False)

        self._sherpa = sherpa_onnx
        self._model_dir = model_dir
        self._tokens = str(model_dir / "tokens.txt")
        self._lexicon = str(model_dir / "en.phone")

        self._spotters: dict[str, Any] = {}
        self._profiles: dict[str, str] = {}
        self._streams: dict[tuple[str, str], Any] = {}
        self._warmed_profiles: set[str] = set()

    def run(self, data: bytes) -> bytes:
        header, payload = decode_packet(data)
        operation = InvocationRunnerOperation(header["operation"])

        if operation == InvocationRunnerOperation.WARMUP:
            profile = header.get("profile")
            if profile is None:
                raise ValueError("Invocation warmup requires a keyword profile")

            self._warmup(profile)
            return encode_response()

        stream_id = str(header["stream_id"])
        profile = header["profile"]
        stream_key = str(profile["profile_id"]), stream_id

        if operation == InvocationRunnerOperation.CLOSE:
            self._streams.pop(stream_key, None)
            return encode_response()

        sample_rate = int(header["sample_rate"])
        num_channels = int(header["num_channels"])
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")

        spotter, stream = self._stream(
            stream_id=stream_id,
            profile=profile,
        )

        samples = self._samples(payload, num_channels=num_channels)
        if samples.size:
            stream.accept_waveform(sample_rate, samples)

        labels = list(self._decode(spotter, stream))

        if operation == InvocationRunnerOperation.FINISH:
            tail_padding_sec = float(header.get("tail_padding_sec", 0.66))
            if tail_padding_sec < 0:
                raise ValueError("tail_padding_sec cannot be negative")

            if tail_padding_sec:
                stream.accept_waveform(
                    sample_rate,
                    np.zeros(
                        round(tail_padding_sec * sample_rate),
                        dtype=np.float32,
                    ),
                )

            stream.input_finished()
            labels.extend(self._decode(spotter, stream))
            self._streams.pop(stream_key, None)

        return encode_response(labels=tuple(dict.fromkeys(labels)))

    def close(self) -> None:
        self._streams.clear()
        self._warmed_profiles.clear()
        self._spotters.clear()
        self._profiles.clear()

        self._sherpa = None
        self._model_dir = None
        self._tokens = ""
        self._lexicon = ""
