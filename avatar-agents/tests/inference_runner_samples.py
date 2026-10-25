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

import time

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


class SlowInitRunner(InferenceRunner):
    INFERENCE_METHOD = "test.slow_init"

    def initialize(self) -> None:
        time.sleep(60)
