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

from dataclasses import dataclass

from ..enums import ModelMediaKind


@dataclass(frozen=True, slots=True)
class ModelMediaPart:
    """Media supplied by a tool, client, or model; constructing it performs no I/O."""

    kind: ModelMediaKind
    mime_type: str
    data: bytes | None = None
    uri: str | None = None
    filename: str | None = None

    def __post_init__(self) -> None:
        if self.filename is not None and (
            not isinstance(self.filename, str)
            or not self.filename.strip()
            or self.filename in {".", ".."}
            or any(character in self.filename for character in ("/", "\\", "\0"))
        ):
            raise ValueError("Media filename must be a nonempty basename")

        if not isinstance(self.kind, ModelMediaKind):
            raise TypeError("kind must be a ModelMediaKind")
        if not isinstance(self.mime_type, str) or not self.mime_type.strip():
            raise ValueError("Media MIME type is required")
        if (self.data is None) == (self.uri is None):
            raise ValueError("Media must contain exactly one of data or uri")
        if self.data is not None and (not isinstance(self.data, bytes) or not self.data):
            raise ValueError("Media data must be nonempty bytes")
        if self.uri is not None and (not isinstance(self.uri, str) or not self.uri.strip()):
            raise ValueError("Media URI must be a nonempty string")
        if self.kind != ModelMediaKind.FILE and not self.mime_type.startswith(f"{self.kind}/"):
            raise ValueError("Media kind and MIME type do not match")
