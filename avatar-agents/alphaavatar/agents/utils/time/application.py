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
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from alphaavatar.agents.log import logger


def resolve_application_timezone(tz: str | None = None) -> str | None:
    """Resolve the AlphaAvatar application timezone."""
    tzname = tz or os.getenv("AVATAR_TIMEZONE")
    if not tzname:
        return None

    try:
        ZoneInfo(tzname)
    except ZoneInfoNotFoundError:
        logger.warning("Invalid application timezone=%s, fallback to server local timezone", tzname)
        return None

    return tzname


def application_now(tz: str | None = None) -> datetime:
    """Return the current application wall-clock time."""
    tzname = resolve_application_timezone(tz)
    return datetime.now(ZoneInfo(tzname)) if tzname else datetime.now().astimezone()
