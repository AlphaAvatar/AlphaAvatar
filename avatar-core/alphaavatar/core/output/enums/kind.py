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


class OutputKind(StrEnum):
    STATUS = "status"
    TEXT_CHUNK = "text_chunk"
    AUDIO_FRAME = "audio_frame"
    ALIGNMENT = "alignment"
    PLAYBACK = "playback"
    TRANSCRIPT_CHUNK = "transcript_chunk"
    CONTROL = "control"


class ExecutionSignalKind(StrEnum):
    ACCEPTED = "accepted"
    MODEL_STARTED = "model_started"
    TOOLS_PENDING = "tools_pending"
    TOOL_STARTED = "tool_started"
    TOOL_FINISHED = "tool_finished"
    FINALIZING = "finalizing"
    FINISHED = "finished"
