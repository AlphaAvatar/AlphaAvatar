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
"""Model-free runners for Doctor's runtime checks; spawned children import them by name.

Doctor launches runners with the start snapshot, so they keep their traces in the
temporary workspace it gives them rather than in a test-chosen directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from alphaavatar.agents.runtime.inference.runner import InferenceRunner


class WitnessRunner(InferenceRunner):
    """Answers with what its own process sees: launch paths, offline loading, the request.

    Each start appends to ``witness.starts`` in the workspace, so an answer also counts the
    processes started for this method.
    """

    INFERENCE_METHOD = "test.doctor.witness"
    REPLICABLE = True

    def initialize(self) -> None:
        with (Path(self.launch.workspace_root) / "witness.starts").open("a") as starts:
            starts.write(f"{os.getpid()}\n")

    def run(self, data: bytes) -> bytes | None:
        from alphaavatar.agents.utils.files.model.model_files import models_offline

        starts = Path(self.launch.workspace_root) / "witness.starts"
        seen = {
            "starts": len(starts.read_text().splitlines()),
            "pid": os.getpid(),
            "workspace": self.launch.workspace_root,
            "models": self.launch.models_dir,
            "offline": models_offline(),
            "hub_offline": os.environ.get("HF_HUB_OFFLINE"),
            "request": hashlib.sha256(data).hexdigest(),
        }
        return json.dumps(seen).encode()


class HeldRunner(InferenceRunner):
    """Its start marks ``held.entered`` in the workspace, then waits for ``held.open``."""

    INFERENCE_METHOD = "test.doctor.held"

    def initialize(self) -> None:
        root = Path(self.launch.workspace_root)
        (root / "held.entered").touch()
        deadline = time.monotonic() + 60
        while not (root / "held.open").exists():
            if time.monotonic() > deadline:
                raise TimeoutError("The test never opened the held start")
            time.sleep(0.002)
