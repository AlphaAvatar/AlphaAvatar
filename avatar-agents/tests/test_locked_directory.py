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
"""The shared directory lock: a persistent lock file, link refusal, release and exclusion."""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path

import filelock
import pytest
from lock_holder import HANG_GUARD, held_elsewhere

from alphaavatar.agents.utils.files.atomic import locked_directory


def test_a_held_lock_excludes_others_and_its_file_stays_after_release(tmp_path: Path) -> None:
    directory = tmp_path / "data"
    lock = directory / ".write.lock"
    with locked_directory(directory):
        assert lock.is_file() and not lock.is_symlink()
        # Another acquisition, even in this process, waits out its timeout instead of entering.
        with pytest.raises(filelock.Timeout):
            with locked_directory(directory, timeout=0.05):
                pytest.fail("Entered a held lock")
    assert lock.is_file()  # The lock library owns the file; nobody deletes it.
    with locked_directory(directory, timeout=0):
        assert lock.is_file()


@pytest.mark.parametrize("error", [RuntimeError, KeyboardInterrupt])
def test_leaving_the_lock_by_an_exception_releases_it(
    error: type[BaseException], tmp_path: Path
) -> None:
    directory = tmp_path / "data"
    with pytest.raises(error):
        with locked_directory(directory):
            raise error("interrupted")
    with locked_directory(directory, timeout=0):
        assert (directory / ".write.lock").is_file()


@pytest.mark.parametrize("target", ["inside", "outside", "dangling"])
def test_a_linked_lock_file_is_refused_and_left_as_it_was(target: str, tmp_path: Path) -> None:
    directory = tmp_path / "data"
    directory.mkdir()
    pointee = {
        "inside": directory / "notes.txt",
        "outside": tmp_path / "outside.txt",
        "dangling": tmp_path / "missing.txt",
    }[target]
    if target != "dangling":
        pointee.write_text("keep me\n")
        pointee.chmod(0o640)
    lock = directory / ".write.lock"
    lock.symlink_to(pointee)

    # Opening it would truncate the target, create the missing one, or change its mode.
    with pytest.raises(OSError) as refused:
        with locked_directory(directory):
            pytest.fail("Entered through a linked lock file")
    assert (refused.value.errno, refused.value.filename) == (errno.ELOOP, str(lock))
    assert lock.is_symlink() and os.readlink(lock) == str(pointee)
    if target == "dangling":
        assert not pointee.exists()
    else:
        assert pointee.read_text() == "keep me\n"
        assert stat.S_IMODE(pointee.stat().st_mode) == 0o640


def test_two_processes_exclude_each_other(tmp_path: Path) -> None:
    directory = tmp_path / "data"
    with held_elsewhere(directory, tmp_path) as release:
        with pytest.raises(filelock.Timeout):
            with locked_directory(directory, timeout=0.2):
                pytest.fail("Entered a lock another process holds")
        release.touch()
        with locked_directory(directory, timeout=HANG_GUARD):
            assert (directory / ".write.lock").is_file()
