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

from typing import Any

from .enum.formats import PayloadFormat, PayloadView
from .payload import MediaPayload


class TextPayload(MediaPayload):
    def __init__(
        self,
        *,
        language: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(modality="text", metadata=metadata)
        self.language = language

    @classmethod
    def create(
        cls,
        *,
        text: str,
        language: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TextPayload:
        normalized = text.strip()
        if not normalized:
            raise ValueError("Text payload cannot be empty")

        payload = cls(language=language, metadata=metadata)
        payload.put(PayloadFormat.TEXT, normalized, view=PayloadView.RAW)
        return payload

    @property
    def text(self) -> str:
        return self.get(PayloadFormat.TEXT, view=PayloadView.RAW, fallback_to_raw=False)
