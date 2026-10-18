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

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ConversationLogConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    content: Literal["off", "dev", "all"] = "dev"
    max_chars: int = Field(default=2048, strict=True, ge=128, le=4096)
    file_content: bool = False


class LogConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] | None = None
    third_party_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    color: Literal["auto", "always", "never"] = "auto"
    banner: bool = True
    events: bool = False
    conversation: ConversationLogConfig = Field(default_factory=ConversationLogConfig)
    file: bool = True
    directory: str | None = Field(default=None, min_length=1)
    rotate_bytes: int = Field(default=10_485_760, strict=True, ge=1024)
    backup_count: int = Field(default=3, strict=True, ge=1, le=100)
    shutdown_timeout: float = Field(default=3.0, gt=0, le=30)
