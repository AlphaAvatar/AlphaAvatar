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
import logging
import time
from collections.abc import Hashable
from threading import Lock
from typing import Any

DEV_LEVEL = 23
logging.addLevelName(DEV_LEVEL, "DEV")

logger = logging.getLogger("alphaavatar.agents")

_last_log_times: dict[Hashable, float] = {}
_suppressed_counts: dict[Hashable, int] = {}
_log_lock = Lock()


def _log_every(
    level: int,
    msg: str,
    *args: Any,
    key: Hashable | None = None,
    interval_sec: float = 10.0,
    include_suppressed: bool = True,
    **kwargs: Any,
) -> None:
    """
    Rate-limited logging helper.

    Logs the same key at most once every `interval_sec` seconds.
    Useful for high-frequency realtime paths such as face/speaker inference.
    """
    if interval_sec <= 0:
        logger.log(level, msg, *args, **kwargs)
        return

    log_key = key if key is not None else (level, msg)
    now = time.monotonic()

    with _log_lock:
        last_time = _last_log_times.get(log_key)

        if last_time is not None and now - last_time < interval_sec:
            _suppressed_counts[log_key] = _suppressed_counts.get(log_key, 0) + 1
            return

        _last_log_times[log_key] = now
        suppressed = _suppressed_counts.pop(log_key, 0)

    if include_suppressed and suppressed > 0:
        msg = f"{msg} [suppressed=%s]"
        args = (*args, suppressed)

    logger.log(level, msg, *args, **kwargs)


def debug_every(
    msg: str,
    *args: Any,
    key: Hashable | None = None,
    interval_sec: float = 10.0,
    **kwargs: Any,
) -> None:
    _log_every(
        logging.DEBUG,
        msg,
        *args,
        key=key,
        interval_sec=interval_sec,
        **kwargs,
    )


def info_every(
    msg: str,
    *args: Any,
    key: Hashable | None = None,
    interval_sec: float = 10.0,
    **kwargs: Any,
) -> None:
    _log_every(
        logging.INFO,
        msg,
        *args,
        key=key,
        interval_sec=interval_sec,
        **kwargs,
    )


def warning_every(
    msg: str,
    *args: Any,
    key: Hashable | None = None,
    interval_sec: float = 30.0,
    **kwargs: Any,
) -> None:
    _log_every(
        logging.WARNING,
        msg,
        *args,
        key=key,
        interval_sec=interval_sec,
        **kwargs,
    )


def dev_every(
    msg: str,
    *args: Any,
    key: Hashable | None = None,
    interval_sec: float = 10.0,
    **kwargs: Any,
) -> None:
    _log_every(
        DEV_LEVEL,
        msg,
        *args,
        key=key,
        interval_sec=interval_sec,
        **kwargs,
    )
