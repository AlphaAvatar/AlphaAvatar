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

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def resolve_application_timezone(tz: str | None = None) -> str | None:
    """Validate an explicitly supplied timezone without process-wide state."""
    if tz is None:
        return None

    try:
        ZoneInfo(tz)
    except ZoneInfoNotFoundError:
        raise ValueError(f"Unknown application timezone: {tz}") from None
    return tz


def application_now(tz: str | None = None) -> datetime:
    """Persist UTC by default; presentation may request an explicit timezone."""
    tzname = resolve_application_timezone(tz)
    return datetime.now(ZoneInfo(tzname) if tzname else UTC)
