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
import calendar
import os
import random
import time
from datetime import datetime

from pydantic import BaseModel, Field

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except Exception:
    ZoneInfo = None  # type: ignore
    ZoneInfoNotFoundError = Exception  # type: ignore

from alphaavatar.agents.log import logger


class AvatarTime(BaseModel):
    timezone: str = Field(default_factory=str)
    year: str = Field(default_factory=str)
    month: str = Field(default_factory=str)
    day: str = Field(default_factory=str)
    time_str: str = Field(default_factory=str)


def _now_in_tz(tzname: str) -> datetime:
    """
    Return current time in the given IANA timezone.
    Tries zoneinfo first; if unavailable or tz not found, falls back to pytz.
    """
    if ZoneInfo:
        try:
            return datetime.now(ZoneInfo(tzname))
        except ZoneInfoNotFoundError:
            pass

    try:
        import pytz
    except Exception as e:
        raise ImportError(
            "Timezone support requires either 'zoneinfo' Python 3.9+ or 'pytz'. "
            "Install pytz or upgrade Python."
        ) from e

    return datetime.now(pytz.timezone(tzname))


def resolve_timezone(tz: str | None = None) -> tuple[str | None, str]:
    """
    Resolve timezone by priority:

    1. Explicit tz argument
    2. AVATAR_TIMEZONE env
    3. None, meaning server local time

    Returns:
        tuple[timezone, source]
    """
    if tz:
        return tz, "metadata"

    env_tz = os.getenv("AVATAR_TIMEZONE")
    if env_tz:
        return env_tz, "env"

    return None, "server"


def format_current_time(tz: str | None = None) -> AvatarTime:
    """
    Return the current time in a stable prompt-friendly format.

    Args:
        tz: IANA timezone name, e.g. "Asia/Dubai", "America/Los_Angeles".

    Returns:
        AvatarTime
    """
    resolved_tz, source = resolve_timezone(tz)

    try:
        dt = _now_in_tz(resolved_tz) if resolved_tz else datetime.now()
    except Exception as e:
        logger.warning("Invalid timezone=%s, fallback to server local time: %s", resolved_tz, e)
        resolved_tz = None
        source = "server_fallback"
        dt = datetime.now()

    weekday = calendar.day_name[dt.weekday()]
    month = calendar.month_name[dt.month]

    hour12 = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"

    minute = f"{dt.minute:02d}"

    timezone_display = resolved_tz or "Server Local Time"

    time_str = (
        f"Timezone: {timezone_display}; "
        f"Timezone Source: {source}; "
        f"Time: {weekday}, {month} {dt.day}, {dt.year}, {hour12}:{minute} {ampm}"
    )

    return AvatarTime(
        timezone=timezone_display,
        year=str(dt.year),
        month=str(dt.month),
        day=str(dt.day),
        time_str=time_str,
    )


def build_time_context_from_metadata(metadata: dict) -> dict:
    """
    Build prompt-ready time context from participant metadata.

    Expected metadata examples:
        {
            "timezone": "Asia/Dubai",
            "timezone_source": "browser",
            "last_session_timezone": "America/Los_Angeles",
            "last_session_time": "Tuesday, May 5, 2026, 10:10 PM"
        }
    """
    timezone = metadata.get("timezone") or metadata.get("browser_timezone") or metadata.get("tz")

    timezone_source = metadata.get(
        "timezone_source",
        "browser" if timezone else "server",
    )

    current = format_current_time(timezone)

    return {
        "current_time": current.time_str,
        "current_timezone": current.timezone,
        "timezone_source": timezone_source,
        "last_session_timezone": metadata.get("last_session_timezone", "Unknown"),
        "last_session_time": metadata.get("last_session_time", "Unknown"),
    }


def time_str_to_datetime(time_str: str) -> datetime:
    try:
        time_part = time_str.split("Time:")[1].strip()

        try:
            return datetime.strptime(time_part, "%A, %B %d, %Y, %I:%M %p")
        except ValueError:
            return datetime.strptime(time_part, "%A, %B %d, %Y, %I %p")

    except Exception as e:
        logger.error(f"Unable to resolve timestamp: {time_str}. Error: {e}")
        return datetime.min


def get_timestamp() -> str:
    return f"{int(time.time() * 1000)}{random.randint(100, 999)}"
