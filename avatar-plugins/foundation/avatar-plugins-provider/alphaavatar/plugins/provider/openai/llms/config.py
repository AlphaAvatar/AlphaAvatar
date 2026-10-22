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
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class OpenAIClientConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    api_key: SecretStr | None = None
    api_key_env: str = Field(default="OPENAI_API_KEY", min_length=1)
    base_url: str = "https://api.openai.com/v1"
    organization: str | None = None
    project: str | None = None
    proxy: str | None = None
    max_retries: int = Field(default=0, ge=0, le=3)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            raise ValueError("OpenAI base_url must be an HTTP(S) endpoint")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("OpenAI base_url cannot embed credentials, queries, or fragments")
        return value.rstrip("/")


class ResponsesInputConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    image_detail: Literal["auto", "low", "high"] = "auto"
    jpeg_quality: int = Field(default=85, ge=1, le=100)
    max_inline_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    max_output_chars: int = Field(default=4 * 1024 * 1024, gt=0)
    max_output_items: int = Field(default=256, gt=0)
