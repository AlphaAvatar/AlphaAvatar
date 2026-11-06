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
"""A third-party package's runner in the plugins' own namespace, as any package may ship one.

Its module path looks like a built-in one; it declares nothing of what its start reaches, so
Doctor must not take it for local. Its start leaves a mark in the test's files, so a test sees
whether it ran.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from alphaavatar.agents.runtime.inference.runner import InferenceRunner


class ThirdPartyRunner(InferenceRunner):
    INFERENCE_METHOD = "thirdparty.doctor.runner"

    def initialize(self) -> None:
        files = Path(json.loads(os.environ["DOCTOR_DOUBLES"])["files"])
        (files / "thirdparty").write_text(str(os.getpid()))

    def run(self, data: bytes) -> bytes | None:
        return data
