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

from threading import RLock
from typing import Any

from .formats import PayloadFormat, PayloadView


class PayloadFormatUnavailable(LookupError):
    """Requested payload representation is unavailable."""


class MediaPayload:
    """
    Multi-representation runtime media payload.

    One logical media item can expose several representations:

        RAW + VIDEO_FRAME
        RAW + IMAGE_JPEG_BYTES
        ANNOTATED + VIDEO_FRAME
        ANNOTATED + IMAGE_JPEG_BYTES

    Consumers explicitly request the representation they need.
    """

    def __init__(
        self,
        *,
        modality: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.modality = modality
        self.metadata = metadata or {}

        self._representations: dict[
            tuple[PayloadView, PayloadFormat],
            Any,
        ] = {}

        self._lock = RLock()
        self._revision = 0

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    @property
    def has_any(self) -> bool:
        with self._lock:
            return bool(self._representations)

    def put(
        self,
        fmt: PayloadFormat,
        value: Any,
        *,
        view: PayloadView = PayloadView.RAW,
    ) -> None:
        if value is None:
            raise ValueError(f"Cannot store None payload representation: view={view}, format={fmt}")

        with self._lock:
            self._representations[(view, fmt)] = value
            self._revision += 1

    def has(
        self,
        fmt: PayloadFormat,
        *,
        view: PayloadView = PayloadView.RAW,
        fallback_to_raw: bool = True,
    ) -> bool:
        with self._lock:
            if (view, fmt) in self._representations:
                return True

            if fallback_to_raw and view != PayloadView.RAW:
                return (PayloadView.RAW, fmt) in self._representations

            return False

    def get(
        self,
        fmt: PayloadFormat,
        *,
        view: PayloadView = PayloadView.RAW,
        fallback_to_raw: bool = True,
    ) -> Any:
        with self._lock:
            key = (view, fmt)

            if key in self._representations:
                return self._representations[key]

            if fallback_to_raw and view != PayloadView.RAW:
                raw_key = (PayloadView.RAW, fmt)
                if raw_key in self._representations:
                    return self._representations[raw_key]

        raise PayloadFormatUnavailable(
            "Payload representation unavailable: "
            f"modality={self.modality!r}, "
            f"view={view.value!r}, "
            f"format={fmt.value!r}"
        )

    def remove(
        self,
        fmt: PayloadFormat,
        *,
        view: PayloadView,
    ) -> None:
        with self._lock:
            removed = self._representations.pop((view, fmt), None)
            if removed is not None:
                self._revision += 1

    def clear(self) -> None:
        with self._lock:
            self._representations.clear()
            self._revision += 1

    def available_representations(
        self,
    ) -> tuple[tuple[PayloadView, PayloadFormat], ...]:
        with self._lock:
            return tuple(self._representations.keys())
