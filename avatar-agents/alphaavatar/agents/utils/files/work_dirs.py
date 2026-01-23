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
import os
import pathlib
import re

from pydantic import BaseModel, ConfigDict, Field

_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


class UserPath(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: str = Field(..., description="Sanitized user id used in folder names.")
    user_root: pathlib.Path

    data_dir: pathlib.Path
    cache_dir: pathlib.Path
    logs_dir: pathlib.Path


def _can_write_dir(path: pathlib.Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        test = path / ".write_test"
        test.write_text("ok", encoding="utf-8")
        test.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def default_work_dir(app_name: str) -> pathlib.Path:
    # Preferred server path
    preferred = pathlib.Path("/var/lib") / app_name
    if _can_write_dir(preferred):
        return preferred

    # Fallback for non-root user
    home = pathlib.Path.home()
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return pathlib.Path(xdg) / app_name
    return home / ".local" / "share" / app_name


def sanitize_id(s: str, max_len: int = 64) -> str:
    s = (s or "").strip()
    s = _SAFE.sub("_", s)
    s = s.strip("._-")
    if not s:
        s = "unknown"
    return s[:max_len]


def mk_user_dirs(work_dir: str, user_id: str) -> UserPath:
    base = pathlib.Path(work_dir)
    uid = sanitize_id(user_id)

    user_root = base / "users" / uid
    data_dir = user_root / "data"
    cache_dir = user_root / ".cache"
    logs_dir = user_root / "logs"

    for d in [data_dir, cache_dir, logs_dir]:
        d.mkdir(parents=True, exist_ok=True)

    return UserPath(
        user_id=uid,
        user_root=user_root,
        data_dir=data_dir,
        cache_dir=cache_dir,
        logs_dir=logs_dir,
    )
