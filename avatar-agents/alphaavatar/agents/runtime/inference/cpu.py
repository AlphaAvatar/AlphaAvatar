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
import re
from collections.abc import Iterator
from pathlib import Path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return ""


def _unescape(value: str) -> Path:
    return Path(re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), value))


def _cpu_quotas() -> Iterator[float]:
    groups = [line.split(":", 2) for line in _read_text(Path("/proc/self/cgroup")).splitlines()]
    for line in _read_text(Path("/proc/self/mountinfo")).splitlines():
        before, separator, after = line.partition(" - ")
        fields, mount = before.split(), after.split()
        if not separator or len(fields) < 6 or len(mount) < 3:
            continue
        unified = mount[0] == "cgroup2"
        if not unified and not (mount[0] == "cgroup" and "cpu" in mount[2].split(",")):
            continue
        root, point = _unescape(fields[3]), _unescape(fields[4])
        for group in groups:
            if len(group) != 3 or (group[1] != "" if unified else "cpu" not in group[1].split(",")):
                continue
            member = Path(group[2])
            if not member.is_absolute() or ".." in member.parts:
                continue
            try:
                relative = member.relative_to(root)
            except ValueError:
                if member != Path("/"):
                    continue
                relative = Path(".")  # A cgroup namespace can expose the mounted group as root.
            directory = point / relative
            while directory.is_relative_to(point):
                try:
                    if unified:
                        quota, period = _read_text(directory / "cpu.max").split()
                    else:
                        quota = _read_text(directory / "cpu.cfs_quota_us")
                        period = _read_text(directory / "cpu.cfs_period_us")
                    quota, period = int(quota), int(period)
                    if quota > 0 and period > 0:
                        yield quota / period
                except ValueError:
                    pass
                if directory == point:
                    break
                directory = directory.parent


def available_cpu_count() -> float:
    """Estimate visible CPU capacity once during runner initialization, not on the media loop."""
    count = float(os.cpu_count() or 1)
    try:
        count = min(count, float(len(os.sched_getaffinity(0))))
    except (AttributeError, OSError):
        pass
    return min([count if count > 0 else 1.0, *_cpu_quotas()])
