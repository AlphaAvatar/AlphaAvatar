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
from datetime import datetime

# Try zoneinfo first (Py>=3.9); if unavailable or tz not found, fall back to pytz.
try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError  # Python 3.9+

    _HAVE_ZONEINFO = True
except Exception:
    ZoneInfo = None  # type: ignore
    ZoneInfoNotFoundError = Exception  # type: ignore
    _HAVE_ZONEINFO = False


def _now_in_tz(tzname: str) -> datetime:
    """
    Return current time in the given IANA timezone.
    Tries zoneinfo first; if unavailable or tz not found, falls back to pytz.
    """
    if _HAVE_ZONEINFO:
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


def format_current_time(tz: str | None = None) -> dict:
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
    dt = datetime.now() if tz is None else _now_in_tz(tz)

    weekday = calendar.day_name[dt.weekday()]  # e.g., "Monday"
    month = calendar.month_name[dt.month]  # e.g., "August"

    # 24h -> 12h conversion and AM/PM
    hour12 = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"

    time_str = f"{weekday}, {month} {dt.day}, {dt.year}, {hour12} {ampm}"
    return {
        "year": dt.year,
        "month": dt.month,
        "day": dt.day,
        "time_str": time_str,
    }
