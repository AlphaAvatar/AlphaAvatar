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

import calendar
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel

from alphaavatar.agents.log import logger

from .application import resolve_application_timezone


class UserTimeContext(BaseModel):
    timezone: str | None = None
    timezone_display: str = ""
    timezone_source: str = ""

    year: str = ""
    month: str = ""
    day: str = ""
    time_str: str = ""


class ParticipantTimeContext(BaseModel):
    participant_id: str
    user_id: str | None = None
    user_time: UserTimeContext


def _resolve_user_timezone(metadata: dict | None = None) -> tuple[str | None, str]:
    """
    Resolve user-facing timezone by priority:

    1. Participant/browser metadata
    2. AlphaAvatar application timezone
    3. Server local timezone
    """
    metadata = metadata or {}

    timezone = metadata.get("timezone") or metadata.get("browser_timezone") or metadata.get("tz")
    if timezone:
        return str(timezone), str(metadata.get("timezone_source") or "browser")

    application_timezone = resolve_application_timezone()
    if application_timezone:
        return application_timezone, "application"

    return None, "server"


def _user_now(timezone: str | None) -> datetime:
    if timezone is None:
        return datetime.now().astimezone()

    try:
        return datetime.now(ZoneInfo(timezone))
    except ZoneInfoNotFoundError:
        raise ValueError(f"Unknown user timezone: {timezone}") from None


def format_user_time(
    timezone: str | None,
    timezone_source: str,
) -> UserTimeContext:
    dt = _user_now(timezone)

    weekday = calendar.day_name[dt.weekday()]
    month = calendar.month_name[dt.month]
    hour12 = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    timezone_display = timezone or str(dt.tzinfo)

    time_str = (
        f"Timezone: {timezone_display}; "
        f"Timezone Source: {timezone_source}; "
        f"Time: {weekday}, {month} {dt.day}, {dt.year}, "
        f"{hour12}:{dt.minute:02d} {ampm}"
    )

    return UserTimeContext(
        timezone=timezone,
        timezone_display=timezone_display,
        timezone_source=timezone_source,
        year=str(dt.year),
        month=str(dt.month),
        day=str(dt.day),
        time_str=time_str,
    )


def format_datetime_for_timezone(value: datetime, timezone: str | None = None) -> str:
    dt = value

    if timezone:
        try:
            dt = value.astimezone(ZoneInfo(timezone))
        except ZoneInfoNotFoundError:
            logger.warning("Invalid timezone=%s while formatting datetime", timezone)

    weekday = calendar.day_name[dt.weekday()]
    month = calendar.month_name[dt.month]
    hour12 = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    timezone_display = timezone or str(dt.tzinfo)

    return (
        f"{weekday}, {month} {dt.day}, {dt.year}, "
        f"{hour12}:{dt.minute:02d} {ampm} ({timezone_display})"
    )


def build_user_time_context(metadata: dict | None = None) -> UserTimeContext:
    timezone, source = _resolve_user_timezone(metadata)
    return format_user_time(timezone, source)
