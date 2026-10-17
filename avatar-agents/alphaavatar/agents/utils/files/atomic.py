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
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager

from filelock import FileLock


@contextmanager
def locked_directory(path: pathlib.Path, *, timeout: float = 10.0) -> Iterator[None]:
    """Serialize cooperating local writers. Call from owned worker threads, not an event loop."""
    path.mkdir(parents=True, exist_ok=True)
    # The lock library owns its sidecar lifecycle; writers must not unlink it manually.
    with FileLock(str(path / ".write.lock"), timeout=timeout):
        yield


def write_text_atomic(path: pathlib.Path, text: str) -> None:
    """Replace one complete UTF-8 file using an exclusive same-directory temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = pathlib.Path(stream.name)
            stream.write(text)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
