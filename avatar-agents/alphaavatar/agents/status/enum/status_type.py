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
from enum import StrEnum


class StatusType(StrEnum):
    THINKING = "thinking"

    TOOL_START = "tool_start"
    TOOL_PROGRESS = "tool_progress"
    TOOL_END = "tool_end"
    TOOL_ERROR = "tool_error"

    RETRIEVAL_START = "retrieval_start"
    RETRIEVAL_PROGRESS = "retrieval_progress"
    RETRIEVAL_END = "retrieval_end"

    FINALIZING = "finalizing"
