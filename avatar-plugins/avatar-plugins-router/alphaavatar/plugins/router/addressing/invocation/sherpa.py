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
import json
from collections import deque
from dataclasses import dataclass, field

from alphaavatar.agents.interaction import (
    InvocationDetection,
    InvocationDetectorBase,
    InvocationDetectorStreamBase,
    InvocationPhrase,
)
from alphaavatar.agents.runtime.inference import InferenceExecutor
from alphaavatar.core.env import (
    PerceptionSegmentRef,
    PerceptionSourceRef,
)
from alphaavatar.core.media import (
    AudioFrame,
    AudioSampleFormat,
)

from ...log import logger
from .runner.sherpa import SherpaKeywordSpotterRunner
from .wire import (
    InvocationRunnerOperation,
    decode_response,
    encode_packet,
)


def _stream_id(segment: PerceptionSegmentRef) -> str:
    serialized = json.dumps(
        segment.to_dict(),
        separators=(",", ":"),
        sort_keys=True,
    ).encode()

    return hashlib.sha256(serialized).hexdigest()


@dataclass(slots=True)
class _SegmentBuffer:
    sample_rate: int
    num_channels: int
    data: bytearray = field(default_factory=bytearray)
    submitted_samples: int = 0
    last_observation_id: str = ""


@dataclass(frozen=True, slots=True)
class _Push:
    segment: PerceptionSegmentRef
    observation_id: str
    sample_rate: int
    num_channels: int
    pcm16_bytes: bytes
    stream_offset_sec: float


@dataclass(frozen=True, slots=True)
class _Finish:
    segment: PerceptionSegmentRef
    observation_id: str
    sample_rate: int
    num_channels: int
    pcm16_bytes: bytes
    stream_offset_sec: float
    discarded: bool


@dataclass(frozen=True, slots=True)
class _Stop:
    pass


class SherpaInvocationDetectorStream(InvocationDetectorStreamBase):
    def __init__(
        self,
        *,
        detector: SherpaInvocationDetector,
        source: PerceptionSourceRef,
        chunk_duration_ms: int,
        max_pending_chunks: int,
        tail_padding_sec: float,
    ) -> None:
        self._detector = detector
        self._source = source
        self._chunk_duration_ms = chunk_duration_ms
        self._max_pending_chunks = max_pending_chunks
        self._tail_padding_sec = tail_padding_sec

        self._buffers: dict[
            PerceptionSegmentRef,
            _SegmentBuffer,
        ] = {}
        self._discarded: set[PerceptionSegmentRef] = set()
        self._opened: set[PerceptionSegmentRef] = set()
        self._detected: dict[PerceptionSegmentRef, set[str]] = {}

        self._commands: deque[_Push | _Finish | _Stop] = deque()
        self._pending_chunks = 0
        self._wake = asyncio.Event()

        self._results: asyncio.Queue[InvocationDetection | None] = asyncio.Queue()

        self._dropped_chunks = 0
        self._closed = False
        self._worker_task = asyncio.create_task(
            self._worker(),
            name=(f"router_invocation:{source.source_id}:{source.source_generation}"),
        )

    @property
    def dropped_chunks(self) -> int:
        return self._dropped_chunks

    def _take_push(self, first: _Push) -> _Push:
        chunks = [first.pcm16_bytes]
        last = first
        count = 1

        while self._commands:
            command = self._commands[0]

            if not isinstance(command, _Push) or command.segment != first.segment:
                break

            self._commands.popleft()
            chunks.append(command.pcm16_bytes)
            last = command
            count += 1

        self._pending_chunks = max(0, self._pending_chunks - count)

        if count == 1:
            return first

        return _Push(
            segment=first.segment,
            observation_id=last.observation_id,
            sample_rate=first.sample_rate,
            num_channels=first.num_channels,
            pcm16_bytes=b"".join(chunks),
            stream_offset_sec=last.stream_offset_sec,
        )

    def push_frame(
        self,
        frame: AudioFrame,
        *,
        segment: PerceptionSegmentRef,
        observation_id: str,
    ) -> bool:
        if self._closed or self._worker_task.done():
            return False
        if segment.source != self._source:
            raise ValueError("Invocation segment source does not match detector stream")
        if frame.sample_format != AudioSampleFormat.PCM_S16LE:
            raise ValueError(
                f"Invocation detector requires PCM_S16LE, got {frame.sample_format.value}"
            )
        if segment in self._discarded:
            return False

        state = self._buffers.get(segment)
        if state is None:
            state = _SegmentBuffer(
                sample_rate=frame.sample_rate,
                num_channels=frame.num_channels,
            )
            self._buffers[segment] = state
        elif state.sample_rate != frame.sample_rate or state.num_channels != frame.num_channels:
            self._discarded.add(segment)
            state.data.clear()
            return False

        state.data.extend(frame.data)
        state.last_observation_id = observation_id

        chunk_samples = max(1, round(state.sample_rate * self._chunk_duration_ms / 1000))
        chunk_bytes = chunk_samples * state.num_channels * 2

        while len(state.data) >= chunk_bytes:
            if self._pending_chunks >= self._max_pending_chunks:
                self._dropped_chunks += 1
                self._discarded.add(segment)
                state.data.clear()
                return False

            pcm16_bytes = bytes(state.data[:chunk_bytes])
            del state.data[:chunk_bytes]

            state.submitted_samples += chunk_samples
            self._commands.append(
                _Push(
                    segment=segment,
                    observation_id=observation_id,
                    sample_rate=state.sample_rate,
                    num_channels=state.num_channels,
                    pcm16_bytes=pcm16_bytes,
                    stream_offset_sec=state.submitted_samples / state.sample_rate,
                )
            )
            self._pending_chunks += 1

        self._wake.set()
        return True

    def finish_segment(self, segment: PerceptionSegmentRef) -> bool:
        state = self._buffers.pop(segment, None)
        if state is None:
            return False

        discarded = segment in self._discarded
        pcm16_bytes = b"" if discarded else bytes(state.data)

        if pcm16_bytes:
            state.submitted_samples += len(pcm16_bytes) // (state.num_channels * 2)

        self._commands.append(
            _Finish(
                segment=segment,
                observation_id=state.last_observation_id,
                sample_rate=state.sample_rate,
                num_channels=state.num_channels,
                pcm16_bytes=pcm16_bytes,
                stream_offset_sec=state.submitted_samples / state.sample_rate,
                discarded=discarded,
            )
        )
        self._wake.set()
        return not discarded

    async def _close_remote_stream(self, segment: PerceptionSegmentRef) -> None:
        if segment not in self._opened:
            return

        try:
            await self._detector.close_stream(segment)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "Failed to close invocation stream segment=%s",
                segment.segment_id,
                exc_info=True,
            )
        finally:
            self._opened.discard(segment)

    async def __anext__(self) -> InvocationDetection:
        result = await self._results.get()
        if result is None:
            raise StopAsyncIteration
        return result

    async def _emit(
        self,
        *,
        segment: PerceptionSegmentRef,
        observation_id: str,
        stream_offset_sec: float,
        labels: tuple[str, ...],
    ) -> None:
        seen = self._detected.setdefault(segment, set())

        for phrase_id in labels:
            if phrase_id in seen:
                continue

            phrase = self._detector.phrases_by_id.get(phrase_id)
            if phrase is None:
                logger.warning(
                    "Unknown invocation label phrase_id=%s",
                    phrase_id,
                )
                continue

            seen.add(phrase_id)

            await self._results.put(
                InvocationDetection(
                    segment=segment,
                    observation_id=observation_id,
                    phrase_id=phrase.phrase_id,
                    phrase=phrase.text,
                    stream_offset_sec=stream_offset_sec,
                )
            )

    async def _worker(self) -> None:
        try:
            while True:
                await self._wake.wait()
                self._wake.clear()

                while self._commands:
                    command = self._commands.popleft()

                    if isinstance(command, _Stop):
                        for segment in tuple(self._opened):
                            await self._close_remote_stream(segment)
                        return

                    if isinstance(command, _Push):
                        command = self._take_push(command)

                        if command.segment in self._discarded:
                            continue

                        try:
                            labels = await self._detector.push(command)
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            self._discarded.add(command.segment)
                            logger.exception(
                                "Invocation inference failed segment=%s",
                                command.segment.segment_id,
                            )
                            await self._close_remote_stream(command.segment)
                            continue

                        self._opened.add(command.segment)
                        await self._emit(
                            segment=command.segment,
                            observation_id=command.observation_id,
                            stream_offset_sec=command.stream_offset_sec,
                            labels=labels,
                        )
                        continue

                    try:
                        if command.discarded or command.segment in self._discarded:
                            await self._close_remote_stream(command.segment)
                        else:
                            labels = await self._detector.finish(
                                command,
                                tail_padding_sec=self._tail_padding_sec,
                            )
                            await self._emit(
                                segment=command.segment,
                                observation_id=command.observation_id,
                                stream_offset_sec=command.stream_offset_sec,
                                labels=labels,
                            )
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception(
                            "Invocation finalization failed segment=%s",
                            command.segment.segment_id,
                        )
                        await self._close_remote_stream(command.segment)
                    finally:
                        self._opened.discard(command.segment)
                        self._discarded.discard(command.segment)
                        self._detected.pop(command.segment, None)

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Sherpa invocation worker failed source_id=%s generation=%s",
                self._source.source_id,
                self._source.source_generation,
            )
        finally:
            await self._results.put(None)

    async def aclose(self) -> None:
        if self._closed:
            return

        self._closed = True
        self._commands.clear()
        self._pending_chunks = 0
        self._commands.append(_Stop())
        self._wake.set()

        await asyncio.gather(
            self._worker_task,
            return_exceptions=True,
        )

        self._buffers.clear()
        self._discarded.clear()
        self._opened.clear()
        self._detected.clear()


class SherpaInvocationDetector(InvocationDetectorBase):
    def __init__(
        self,
        *,
        inference_executor: InferenceExecutor,
        phrases: tuple[InvocationPhrase, ...],
        chunk_duration_ms: int = 160,
        max_pending_chunks: int = 8,
        tail_padding_sec: float = 0.66,
    ) -> None:
        if not phrases:
            raise ValueError("Invocation detector requires at least one phrase")
        if chunk_duration_ms <= 0:
            raise ValueError("chunk_duration_ms must be positive")
        if max_pending_chunks <= 0:
            raise ValueError("max_pending_chunks must be positive")
        if tail_padding_sec < 0:
            raise ValueError("tail_padding_sec cannot be negative")

        phrase_ids = [phrase.phrase_id for phrase in phrases]
        if len(phrase_ids) != len(set(phrase_ids)):
            raise ValueError("Invocation phrase_id values must be unique")

        self._executor = inference_executor
        self._phrases = phrases
        self._chunk_duration_ms = chunk_duration_ms
        self._max_pending_chunks = max_pending_chunks
        self._tail_padding_sec = tail_padding_sec

        self.phrases_by_id = {phrase.phrase_id: phrase for phrase in phrases}

        profile_payload = [phrase.to_dict() for phrase in phrases]
        self._profile = {
            "profile_id": hashlib.sha256(
                json.dumps(
                    profile_payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode()
            ).hexdigest(),
            "phrases": profile_payload,
        }

    @property
    def provider(self) -> str:
        return "sherpa_onnx"

    @property
    def model(self) -> str:
        return "sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20"

    def stream(
        self,
        *,
        source: PerceptionSourceRef,
    ) -> InvocationDetectorStreamBase:
        return SherpaInvocationDetectorStream(
            detector=self,
            source=source,
            chunk_duration_ms=self._chunk_duration_ms,
            max_pending_chunks=self._max_pending_chunks,
            tail_padding_sec=self._tail_padding_sec,
        )

    def _header(
        self,
        *,
        operation: InvocationRunnerOperation,
        segment: PerceptionSegmentRef,
        sample_rate: int | None = None,
        num_channels: int | None = None,
        tail_padding_sec: float | None = None,
    ) -> dict:
        header = {
            "operation": operation.value,
            "stream_id": _stream_id(segment),
            "profile": self._profile,
        }

        if sample_rate is not None:
            header["sample_rate"] = sample_rate
        if num_channels is not None:
            header["num_channels"] = num_channels
        if tail_padding_sec is not None:
            header["tail_padding_sec"] = tail_padding_sec

        return header

    async def _run(self, header: dict, payload: bytes = b"") -> tuple[str, ...]:
        result = await self._executor.do_inference(
            SherpaKeywordSpotterRunner.INFERENCE_METHOD,
            encode_packet(header, payload),
        )

        if result is None:
            raise RuntimeError("Sherpa invocation runner returned no result")

        return decode_response(result)

    async def push(self, command: _Push) -> tuple[str, ...]:
        return await self._run(
            self._header(
                operation=InvocationRunnerOperation.PUSH,
                segment=command.segment,
                sample_rate=command.sample_rate,
                num_channels=command.num_channels,
            ),
            command.pcm16_bytes,
        )

    async def finish(
        self,
        command: _Finish,
        *,
        tail_padding_sec: float,
    ) -> tuple[str, ...]:
        return await self._run(
            self._header(
                operation=InvocationRunnerOperation.FINISH,
                segment=command.segment,
                sample_rate=command.sample_rate,
                num_channels=command.num_channels,
                tail_padding_sec=tail_padding_sec,
            ),
            command.pcm16_bytes,
        )

    async def close_stream(self, segment: PerceptionSegmentRef) -> None:
        await self._run(
            self._header(
                operation=InvocationRunnerOperation.CLOSE,
                segment=segment,
            )
        )

    async def start(self) -> None:
        await self._run(
            {
                "operation": InvocationRunnerOperation.WARMUP.value,
                "profile": self._profile,
            }
        )

    async def aclose(self) -> None:
        pass
