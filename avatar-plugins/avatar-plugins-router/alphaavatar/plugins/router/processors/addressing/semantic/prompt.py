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

from alphaavatar.agents.router import SemanticAddressingRequest


class SemanticAddressingPrompt:
    _IDENTITIES = "{{avatar_identities}}"
    _FOCUS = "{{previous_focus}}"
    _SEGMENTS = "{{transcript_segments}}"

    def __init__(self, path: str) -> None:
        self._template = open(path, "rb").read().decode("utf-8")
        for placeholder in (self._IDENTITIES, self._FOCUS, self._SEGMENTS):
            if self._template.count(placeholder) != 1:
                raise RuntimeError(f"Invalid Semantic Addressing prompt placeholder: {placeholder}")
        self._constant_prefix = self._template.split(self._IDENTITIES, 1)[0]

    @property
    def constant_prefix(self) -> bytes:
        return self._constant_prefix.encode()

    def render(self, request: SemanticAddressingRequest) -> bytes:
        identities = (
            ", ".join(identity.strip() for identity in request.avatar_identities) or "unknown"
        )
        focus = request.previous_focus.strip() if request.previous_focus else "none"
        segments = (
            "\n".join(
                f"- [{'final' if segment.final else 'interim'}] {segment.text.strip()}"
                for segment in request.transcript_segments
            )
            or "- [interim] (no speech yet)"
        )

        return (
            self._template.replace(self._IDENTITIES, identities)
            .replace(self._FOCUS, focus)
            .replace(self._SEGMENTS, segments)
            .encode()
        )
