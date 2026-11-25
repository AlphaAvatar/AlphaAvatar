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

from pydantic import BaseModel, ConfigDict


class DoctorConfig(BaseModel):
    """What Doctor's runtime diagnosis may do, when no one at a terminal is asked."""

    model_config = ConfigDict(extra="forbid")

    # The runtime diagnosis: the runtime started as start starts it, missing model files
    # downloaded, and the configured services called, some billed per call: model, speech,
    # embeddings, vector stores and tools. Off: only the static checks run, unless a person
    # at a terminal agrees.
    external_services: bool = False
    # The remote vector stores this configuration names hold test data Doctor may write.
    # Off: a configuration with one is not diagnosed at runtime, its real data unprotected.
    test_stores: bool = False
