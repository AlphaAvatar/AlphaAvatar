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

import os
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LiveKitConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    connection_mode: Literal["dispatch", "direct"] = "dispatch"
    room_name: str | None = Field(default=None, min_length=1, max_length=256)
    participant_identity: str | None = Field(default=None, min_length=1, max_length=256)
    connect_timeout: float = Field(default=30.0, strict=True, gt=0)
    participant_timeout: float = Field(default=60.0, strict=True, gt=0)
    registration_timeout: float = Field(default=15.0, strict=True, gt=0)
    reconnect_attempts: int = Field(default=16, strict=True, ge=0)
    status_interval: float = Field(default=2.0, strict=True, gt=0)
    ping_interval: float = Field(default=5.0, strict=True, gt=0)
    pong_timeout: float = Field(default=30.0, strict=True, gt=0)
    max_message_bytes: int = Field(default=1048576, strict=True, ge=1024, le=4194304)

    @model_validator(mode="after")
    def check_mode(self) -> LiveKitConfig:
        if (self.connection_mode == "direct") != (self.room_name is not None):
            raise ValueError("room_name is required only in direct connection mode")
        if self.pong_timeout <= self.ping_interval:
            raise ValueError("pong_timeout must exceed ping_interval")
        return self


def websocket_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in ("ws", "wss", "http", "https")
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(character.isspace() for character in value)
    ):
        raise ValueError("LiveKit URL must not contain credentials, query, or fragment")
    _ = parsed.port
    if parsed.scheme in ("ws", "http") and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Remote LiveKit connections require TLS")
    scheme = {"http": "ws", "https": "wss"}.get(parsed.scheme, parsed.scheme)
    return urlunsplit((scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


@dataclass(frozen=True, slots=True)
class LiveKitCredentials:
    url: str
    api_key: str = field(repr=False)
    api_secret: str = field(repr=False)

    @classmethod
    def from_env(cls) -> LiveKitCredentials:
        url = websocket_url(os.getenv("LIVEKIT_URL", ""))
        key, secret = os.getenv("LIVEKIT_API_KEY", ""), os.getenv("LIVEKIT_API_SECRET", "")
        if not key.strip() or not secret.strip():
            raise ValueError("LIVEKIT_API_KEY and LIVEKIT_API_SECRET are required")
        return cls(url=url, api_key=key, api_secret=secret)
