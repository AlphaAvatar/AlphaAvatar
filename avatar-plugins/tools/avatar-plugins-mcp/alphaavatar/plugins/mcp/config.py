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
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_TIMEOUT = 60.0


class MCPServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, hide_input_in_errors=True)

    url: str = Field(min_length=1, repr=False)
    headers: dict[str, str] | None = Field(default=None, repr=False)
    instruction: str | None = None
    transport: Literal["streamable_http", "sse"] = "streamable_http"
    client_session_timeout_seconds: float = Field(default=DEFAULT_TIMEOUT, strict=True, gt=0)
    close_timeout: float = Field(default=10.0, strict=True, gt=0)
    max_in_flight: int = Field(default=32, strict=True, ge=1, le=256)
    max_tools: int = Field(default=4096, strict=True, ge=1, le=65536)
    max_pages: int = Field(default=64, strict=True, ge=1, le=1024)

    @model_validator(mode="after")
    def check_url(self) -> MCPServerConfig:
        parsed = urlsplit(self.url)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or any(character.isspace() for character in self.url)
        ):
            raise ValueError("MCP URL must be HTTP(S), without embedded credentials or a fragment")
        _ = parsed.port
        if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("Remote MCP endpoints require HTTPS")
        return self
