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

import threading
from typing import ClassVar


class InferenceRunner:
    INFERENCE_METHOD: ClassVar[str]

    registered_runners: ClassVar[dict[str, type[InferenceRunner]]] = {}

    @classmethod
    def register(
        cls,
        runner_cls: type[InferenceRunner],
    ) -> None:
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("Inference runners must be registered on the main thread")

        method = getattr(runner_cls, "INFERENCE_METHOD", "")
        if not method:
            raise ValueError(f"{runner_cls.__name__}.INFERENCE_METHOD cannot be empty")

        existing = cls.registered_runners.get(method)
        if existing is runner_cls:
            return

        if existing is not None:
            raise ValueError(
                f"Inference runner `{method}` already registered "
                f"by {existing.__module__}.{existing.__name__}"
            )

        cls.registered_runners[method] = runner_cls

    def initialize(self) -> None:
        pass

    def run(self, data: bytes) -> bytes | None:
        raise NotImplementedError

    def close(self) -> None:
        pass
