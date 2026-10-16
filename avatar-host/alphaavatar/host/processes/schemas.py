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

from alphaavatar.host.sessions.schemas import SessionRequest

IPC_VERSION = 1
MAX_LAUNCH_BYTES = 4194304
MAX_MESSAGE_BYTES = 16384


class ProcessLaunch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = IPC_VERSION
    execution_id: str = Field(min_length=1, max_length=256)
    port: int = Field(strict=True, ge=1, le=65535)
    ticket: str = Field(min_length=32, max_length=256, repr=False)
    application: str = Field(repr=False)
    request: SessionRequest
    log_level: Literal["INFO", "DEBUG"] = "INFO"
    ipc_timeout: float = Field(default=5.0, strict=True, gt=0, allow_inf_nan=False)


class ProcessMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = IPC_VERSION
    execution_id: str = Field(min_length=1, max_length=256)
    kind: Literal["hello", "ready", "stop", "result"]
    ticket: str = Field(default="", max_length=256, repr=False)
    pid: int = Field(default=0, strict=True, ge=0)
    outcome: Literal["", "success", "failed", "unknown"] = ""
    reason: str = Field(default="", max_length=128, pattern=r"^[a-zA-Z0-9_:.-]*$")


class ProcessResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_id: str
    outcome: Literal["success", "failed", "unknown"]
    reason: str
    exit_code: int | None = None
