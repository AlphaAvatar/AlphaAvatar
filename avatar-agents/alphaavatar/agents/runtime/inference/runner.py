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
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from alphaavatar.agents.workspace.paths import absolute_root

if TYPE_CHECKING:
    from alphaavatar.agents.runtime.plugin import AvatarModule


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


class InferenceRunner:
    INFERENCE_METHOD: ClassVar[str]
    # True only when independent processes may serve this method at once: every request
    # carries its own state, and no store, lock or cache must stay consistent across them.
    REPLICABLE: ClassVar[bool] = False
    # What this runner's code loads beyond its plugin's own requirements, as PEP 508
    # requirements, usually an extra of its plugin: checked before anything starts, and
    # installed by `alphaavatar setup`.
    REQUIRES: ClassVar[tuple[str, ...]] = ()
    # The provider implementations it creates models with, by capability type and name:
    # resolved with the plugins before anything starts.
    PROVIDERS: ClassVar[tuple[tuple[AvatarModule, str], ...]] = ()

    @property
    def launch(self) -> RunnerLaunch:
        launch = getattr(self, "_launch", None)
        if launch is None:
            raise RuntimeError("Configure RunnerLaunch before initializing this runner")
        return launch

    def configure(self, launch: RunnerLaunch) -> None:
        if not isinstance(launch, RunnerLaunch):
            raise TypeError("Inference paths require RunnerLaunch")
        previous = getattr(self, "_launch", None)
        if previous is not None and previous != launch:
            raise RuntimeError("An initialized runner cannot change its workspace")
        self._launch = launch

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
