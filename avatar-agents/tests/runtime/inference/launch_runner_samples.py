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
"""Model-free launch probes; spawned children import them by module name via pytest's pythonpath."""

from __future__ import annotations

import json
import os

from alphaavatar.agents.runtime.inference.runner import InferenceRunner


class LaunchProbeRunner(InferenceRunner):
    INFERENCE_METHOD = "test.launch_probe"

    def initialize(self) -> None:
        self._initialized_with = self.launch

    def run(self, data: bytes) -> bytes | None:
        namespace = data.decode()
        return json.dumps(
            {
                "workspace_root": self.launch.workspace_root,
                "models_dir": self.launch.models_dir,
                "unchanged": self.launch is self._initialized_with,
                "section": self.config_for(namespace),
                # Reported only to show what an ambient lookup would have seen instead.
                "ambient_url": os.environ.get("QDRANT_URL"),
            }
        ).encode()


class LaunchProbeTwinRunner(LaunchProbeRunner):
    """Same method as LaunchProbeRunner; a plan must refuse to carry both."""
