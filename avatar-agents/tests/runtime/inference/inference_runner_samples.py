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
"""Model-free runners; spawned children import them by module name via pytest's pythonpath."""

from __future__ import annotations

import os
import time
from pathlib import Path

from alphaavatar.agents.runtime.inference.runner import InferenceRunner


class EchoRunner(InferenceRunner):
    INFERENCE_METHOD = "test.echo"

    def run(self, data: bytes) -> bytes | None:
        if data == b"none":
            return None
        if data == b"fail":
            raise ValueError("private request detail")
        if data.startswith(b"sleep:"):
            time.sleep(float(data.removeprefix(b"sleep:")))
        return data


class FailingInitRunner(InferenceRunner):
    INFERENCE_METHOD = "test.failing_init"

    def initialize(self) -> None:
        raise RuntimeError("private model path")


class JournalRunner(InferenceRunner):
    """Journal every executed request; ``gate:<name>`` waits until the test opens that gate."""

    INFERENCE_METHOD = "test.journal"

    def initialize(self) -> None:
        self._root = Path(self.config_for("test")["root"])

    def run(self, data: bytes) -> bytes | None:
        with (self._root / f"{self.INFERENCE_METHOD}.journal").open("a") as journal:
            journal.write(f"{os.getpid()} {data.decode()}\n")
        if data == b"pid":
            return str(os.getpid()).encode()
        if data.startswith(b"gate:"):
            name = data.removeprefix(b"gate:").decode()
            (self._root / f"{name}.entered").touch()
            deadline = time.monotonic() + 60
            while not (self._root / f"{name}.open").exists():
                if time.monotonic() > deadline:
                    raise TimeoutError("The test never opened this gate")
                time.sleep(0.002)
        return data


class SecondJournalRunner(JournalRunner):
    INFERENCE_METHOD = "test.journal.second"


class ParallelRunner(JournalRunner):
    """A replicable journal runner; ``init<N>.hold``/``init<N>.fail`` steer the N-th start."""

    INFERENCE_METHOD = "test.parallel"
    REPLICABLE = True

    def initialize(self) -> None:
        super().initialize()
        # Workers start one at a time, so the line count numbers each start.
        inits = self._root / f"{self.INFERENCE_METHOD}.inits"
        with inits.open("a") as journal:
            journal.write(f"{os.getpid()}\n")
        count = len(inits.read_text().splitlines())
        if (self._root / f"init{count}.fail").exists():
            raise RuntimeError("private init detail")
        if (self._root / f"init{count}.hold").exists():
            (self._root / f"init{count}.entered").touch()
            deadline = time.monotonic() + 60
            while not (self._root / f"init{count}.open").exists():
                if time.monotonic() > deadline:
                    raise TimeoutError("The test never opened this initialization gate")
                time.sleep(0.002)

    def run(self, data: bytes) -> bytes | None:
        # ``work:<ms>:<tag>`` occupies the worker for a fixed time and records its span.
        if not data.startswith(b"work:"):
            return super().run(data)
        started = time.monotonic()
        time.sleep(int(data.split(b":")[1]) / 1000)
        with (self._root / f"{self.INFERENCE_METHOD}.spans").open("a") as spans:
            spans.write(f"{os.getpid()} {started} {time.monotonic()} {data.decode()}\n")
        return data


class SecondParallelRunner(ParallelRunner):
    INFERENCE_METHOD = "test.parallel.second"


class SileroProtocolRunner(InferenceRunner):
    """Silero's request and response layout without a model.

    Loud windows are speech. The returned state adds 1000 per speech window and 1 per
    quiet one, so each stream's own history is visible in its state. A window whose first
    sample is ``HELD_SAMPLE`` waits for the test's ``voice.open`` gate.
    """

    INFERENCE_METHOD = "alphaavatar.voice.vad.silero"
    REPLICABLE = True
    HELD_SAMPLE = 12345

    def initialize(self) -> None:
        self._root = Path(self.config_for("test")["root"])

    def run(self, data: bytes) -> bytes | None:
        import numpy as np

        values = np.frombuffer(data, dtype=np.float32)
        if values.size != 512 + 64 + 256:
            raise ValueError("Invalid Silero request size")
        audio, state = values[:512], values[512 + 64 :]
        if abs(audio[0] * 32767 - self.HELD_SAMPLE) < 0.5:
            (self._root / "voice.entered").touch()
            deadline = time.monotonic() + 60
            while not (self._root / "voice.open").exists():
                if time.monotonic() > deadline:
                    raise TimeoutError("The test never opened the voice gate")
                time.sleep(0.002)
        speech = float(np.abs(audio).mean() > 0.1)
        response = np.empty(1 + state.size, dtype=np.float32)
        response[0] = speech
        response[1:] = state + (1000.0 if speech else 1.0)
        return response.tobytes()


class FailingCloseRunner(EchoRunner):
    INFERENCE_METHOD = "test.failing_close"

    def close(self) -> None:
        raise RuntimeError("private close detail")


class ClosingRunner(EchoRunner):
    """A ready runner whose graceful CLOSE path leaves a trace of its close hook."""

    INFERENCE_METHOD = "test.closing"

    def initialize(self) -> None:
        self._root = Path(self.config_for("test")["root"])

    def close(self) -> None:
        (self._root / f"{self.INFERENCE_METHOD}.closed").touch()
