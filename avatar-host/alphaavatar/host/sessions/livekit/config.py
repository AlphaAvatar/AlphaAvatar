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
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LiveKitConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    connection_mode: Literal["dispatch", "direct"] = "dispatch"
    room_name: str | None = Field(default=None, min_length=1, max_length=256)
    device_id: str | None = Field(default=None, min_length=1, max_length=256)
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
    def from_env(cls, env: Mapping[str, str] | None = None) -> LiveKitCredentials:
        """The credentials start reads, from ``env`` (the process environment by default);
        checked offline, never contacting the server."""
        env = os.environ if env is None else env
        names = ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
        if missing := [name for name in names if not env.get(name, "").strip()]:
            listed = (
                ", ".join(missing[:-1]) + " and " + missing[-1] if len(missing) > 1 else missing[0]
            )
            raise ValueError(f"{listed} {'are' if len(missing) > 1 else 'is'} required")
        url = websocket_url(env["LIVEKIT_URL"])
        return cls(url=url, api_key=env["LIVEKIT_API_KEY"], api_secret=env["LIVEKIT_API_SECRET"])
