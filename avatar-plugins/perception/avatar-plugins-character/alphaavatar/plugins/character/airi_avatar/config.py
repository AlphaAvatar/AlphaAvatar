# Copyright 2025 AlphaAvatar project
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

from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AiriConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Serve the pinned AIRI frontend independently; each execution owns its browser only.
    frontend_url: str = "http://127.0.0.1:5173/livekit-avatar"
    video_width: int = Field(default=1280, ge=320, le=3840, strict=True)
    video_height: int = Field(default=720, ge=240, le=2160, strict=True)
    startup_timeout: float = Field(default=60.0, gt=0, le=300, allow_inf_nan=False)
    close_timeout: float = Field(default=10.0, gt=0, le=60, allow_inf_nan=False)
    executable_path: str | None = Field(default=None, min_length=1)
    chromium_sandbox: bool = True

    @field_validator("frontend_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in ("https", "http")
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or any(char.isspace() for char in value)
        ):
            raise ValueError("Character frontend URL must omit credentials, query and fragment")
        if parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("Remote Character frontends require HTTPS")

        try:
            _ = parsed.port
        except ValueError:
            raise ValueError("Invalid Character frontend port") from None

        return value
