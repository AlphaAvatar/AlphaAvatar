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

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..enums import DeepResearchOp


class DeepResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    op: DeepResearchOp = DeepResearchOp.SEARCH
    query: str | None = Field(default=None, min_length=1)
    urls: list[str] | None = Field(default=None, min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_operation(self) -> DeepResearchRequest:
        if self.op in {DeepResearchOp.SEARCH, DeepResearchOp.RESEARCH} and not self.query:
            raise ValueError("Search and research require a nonempty query")
        if self.op in {DeepResearchOp.SCRAPE, DeepResearchOp.DOWNLOAD} and not self.urls:
            raise ValueError("Scrape and download require URLs")
        if self.urls is not None:
            from urllib.parse import urlsplit

            for url in self.urls:
                parsed = urlsplit(url)
                if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                    raise ValueError("URLs must be absolute HTTP(S) URLs")
                if parsed.username or parsed.password:
                    raise ValueError("URLs must not contain credentials")
        return self
