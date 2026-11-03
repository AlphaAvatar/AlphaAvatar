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
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar

from alphaavatar.core.workspace.paths import absolute_root


@dataclass(frozen=True, slots=True)
class RunnerLaunch:
    workspace_root: str
    models_dir: str
    config: str = field(default="{}", repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_root", str(absolute_root(self.workspace_root)))
        object.__setattr__(self, "models_dir", str(absolute_root(self.models_dir)))
        if not isinstance(self.config, str) or not isinstance(json.loads(self.config), dict):
            raise ValueError("Runner configuration must be a JSON object")


@dataclass(frozen=True, slots=True)
class RunnerProbe:
    """A local check of a runner: one fixed request and what its answer must satisfy.

    Doctor sends it through the shared runtime and executor. Describing a probe starts
    nothing and loads no model.
    """

    model: str
    request: bytes
    # The answer's basic contract: a short description, or ValueError.
    check: Callable[[bytes | None], str]
    # Read only, given the models directory: what resolution lacks, or None when cached.
    missing: Callable[[str], str | None]
    # Audio one request carries, for the real-time factor.
    audio_seconds: float | None = None
    # The execution device the runner pins, when it pins one.
    device: str | None = None


class InferenceRunner:
    INFERENCE_METHOD: ClassVar[str]
    # True only when independent processes may serve this method at once: every request
    # carries its own state, and no store, lock or cache must stay consistent across them.
    REPLICABLE: ClassVar[bool] = False

    def configure(self, launch: RunnerLaunch) -> None:
        if not isinstance(launch, RunnerLaunch):
            raise TypeError("Inference paths require RunnerLaunch")
        previous = getattr(self, "_launch", None)
        if previous is not None and previous != launch:
            raise RuntimeError("An initialized runner cannot change its workspace")
        self._launch = launch

    @property
    def launch(self) -> RunnerLaunch:
        launch = getattr(self, "_launch", None)
        if launch is None:
            raise RuntimeError("Configure RunnerLaunch before initializing this runner")
        return launch

    @classmethod
    def probe(cls) -> RunnerProbe | None:
        """Doctor's local check of this runner; without one, Doctor never starts it."""
        return None

    def config_for(self, namespace: str) -> dict[str, Any]:
        value = json.loads(self.launch.config).get(namespace, {})
        if not isinstance(value, dict):
            raise ValueError("Runner configuration sections must be objects")
        return value

    def initialize(self) -> None:
        pass

    def run(self, data: bytes) -> bytes | None:
        raise NotImplementedError

    def close(self) -> None:
        pass
