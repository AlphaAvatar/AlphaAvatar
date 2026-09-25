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
import os
from collections.abc import Mapping
from typing import Any

from alphaavatar.agents.runtime.inference import InferenceRunner


def configure_inference_runners(config: Mapping[str, Any]) -> tuple[type[InferenceRunner], ...]:
    options = config["tools"]["mcp"]
    if not options["enabled"] or not options["servers"] or options["plugin"] != "default":
        return ()
    from .runner import LanceDBRunner

    os.environ["MCP_VDB_INFERENCE_METHOD"] = LanceDBRunner.INFERENCE_METHOD
    return (LanceDBRunner,)
