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

# Try zoneinfo first (Py>=3.9); if unavailable or tz not found, fall back to pytz.
try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError  # Python 3.9+
except Exception:
    ZoneInfo = None  # type: ignore
    ZoneInfoNotFoundError = Exception  # type: ignore

from alphaavatar.agents.log import logger


class AvatarTime(BaseModel):
    timezore: str = Field(default_factory=str)
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
            pass  # will try pytz next

    # pytz fallback (works on Python 3.8 and earlier)
    try:
        import pytz  # pip install pytz
    except Exception as e:
        raise ImportError(
            "Timezone support requires either 'zoneinfo' (Python 3.9+) or 'pytz'. "
            "Install pytz or upgrade Python."
        ) from e
    return datetime.now(pytz.timezone(tzname))


def format_current_time(tz: str | None = None) -> AvatarTime:
    """
    Return the current time as:
        'Weekday, Month D, YYYY, h AM/PM'

    Args:
        tz: IANA timezone name like "Asia/Kolkata" or "Asia/Shanghai".
            If None, use the server's local time (no timezone conversion).

    Returns:
        A formatted time string, e.g.:
        "Monday, August 25, 2025, 3 PM"
    """
    # Use server local time when tz is None; otherwise convert to the given tz.
    tz = os.getenv("AVATAR_TIMEZONE", None)

    try:
        dt = _now_in_tz(tz) if tz else datetime.now()
    except Exception:
        dt = datetime.now()

    weekday = calendar.day_name[dt.weekday()]  # e.g., "Monday"
    month = calendar.month_name[dt.month]  # e.g., "August"

    # 24h -> 12h conversion and AM/PM
    hour12 = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"

    time_str = f"Timezone: {tz}; Time: {weekday}, {month} {dt.day}, {dt.year}, {hour12} {ampm}"
    time_dict = {
        "timezone": tz,
        "year": str(dt.year),
        "month": str(dt.month),
        "day": str(dt.day),
        "time_str": time_str,
    }
    return AvatarTime(**time_dict)


def time_str_to_datetime(time_str: str) -> datetime:
    try:
        time_part = time_str.split("Time:")[1].strip()
        # handle both with and without minutes
        try:
            return datetime.strptime(time_part, "%A, %B %d, %Y, %I:%M %p")
        except ValueError:
            return datetime.strptime(time_part, "%A, %B %d, %Y, %I %p")
    except Exception as e:
        logger.error(f"Unable to resolve timestamp: {time_str}. Error: {e}")
        return datetime.min


def get_timestamp() -> str:
    id = f"{int(time.time() * 1000)}{random.randint(100, 999)}"
    return id
