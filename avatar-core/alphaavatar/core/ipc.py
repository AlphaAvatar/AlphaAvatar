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

import errno
import os
import tempfile

# Portable AF_UNIX bound: sun_path holds 104 bytes on macOS/BSD and 108 on Linux.
MAX_SOCKET_PATH = 100


def private_socket_path(prefix: str, name: str) -> tuple[str, str]:
    """Create a private directory for one local socket; a long temp root falls back to /tmp."""
    parents = [tempfile.gettempdir()]
    if os.name == "posix":
        parents.append("/tmp")
    for parent in dict.fromkeys(parents):
        # mkdtemp appends eight random characters and creates the directory with mode 0700.
        path = os.path.join(parent, f"{prefix}{'x' * 8}", name)
        if len(os.fsencode(path)) <= MAX_SOCKET_PATH and os.path.isdir(parent):
            directory = tempfile.mkdtemp(prefix=prefix, dir=parent)
            return directory, os.path.join(directory, name)
    raise OSError(errno.ENAMETOOLONG, "No temporary directory can hold a local socket path")
