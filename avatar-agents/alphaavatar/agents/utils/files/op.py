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

import pathlib
import shutil


def _can_write_dir(path: pathlib.Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        test = path / ".write_test"
        test.write_text("ok", encoding="utf-8")
        test.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _merge_dirs(src: pathlib.Path, dst: pathlib.Path) -> None:
    """
    Merge src directory into dst directory.

    Existing files in dst are not overwritten.
    This is safer for merging temporary-user artifacts into real-user directory.
    """
    if not src.exists() or src.resolve() == dst.resolve():
        return

    dst.mkdir(parents=True, exist_ok=True)

    for item in src.iterdir():
        target = dst / item.name

        if item.is_dir():
            _merge_dirs(item, target)
        else:
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
