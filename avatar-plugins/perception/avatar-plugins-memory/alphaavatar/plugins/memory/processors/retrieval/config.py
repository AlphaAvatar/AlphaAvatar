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
from pydantic import BaseModel, ConfigDict, Field


class RetrievalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True

    search_context: int = Field(
        default=3,
        description="The number of contexts used for memory searches.",
    )
    recall_num: int = Field(
        default=10,
        description="The number of items to recall from the memory vector database.",
    )
