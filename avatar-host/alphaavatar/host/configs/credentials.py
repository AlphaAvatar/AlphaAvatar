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
"""Credentials `alphaavatar setup` stores for the services it configured.

They live in one private file in the application home's settings, read into the environment
by the commands that load a configuration, after the .env file and never over a variable
already set. Values are never printed, logged or written elsewhere.
"""

from __future__ import annotations

import os
import re
import secrets
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from alphaavatar.host.workspace import ApplicationPaths

NAME = re.compile(r"[A-Z][A-Z0-9_]*")


def _quoted(value: str) -> str:
    # Double quotes, with the backslash escapes python-dotenv reads back.
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def credentials_path(paths: ApplicationPaths) -> Path:
    return paths.settings_dir / "credentials.env"


def load_credentials(paths: ApplicationPaths) -> tuple[str, ...]:
    """Set each stored credential the environment lacks; the names set."""
    from dotenv import dotenv_values

    path = credentials_path(paths)
    if not path.is_file():
        return ()
    loaded = []
    for name, value in dotenv_values(path, interpolate=False).items():
        if value is not None and name not in os.environ:
            os.environ[name] = value
            loaded.append(name)
    return tuple(loaded)


def load_environment(overrides: Sequence[str] = ()) -> None:
    """The .env file start reads (ENV_FILE), then the credentials stored for the home."""
    from alphaavatar.agents.env import init_env

    from .bundles import application_paths

    init_env()  # It may set ALPHAAVATAR_HOME, which chooses the home.
    load_credentials(application_paths(overrides))


def store_credentials(paths: ApplicationPaths, values: Mapping[str, str]) -> Callable[[], None]:
    """Merge values into the private file by one replacement; returns the undo.

    Other stored names keep their values. The undo puts the previous file back, or removes
    the file this call created.
    """
    from dotenv import dotenv_values

    for name, value in values.items():
        if not NAME.fullmatch(name) or not isinstance(value, str) or not value:
            raise ValueError(f"Invalid credential {name}")
        if any(character in value for character in "\r\n\x00"):
            raise ValueError(f"{name} holds a line break")
    path = credentials_path(paths)
    previous = path.read_bytes() if path.is_file() else None
    stored = dotenv_values(path, interpolate=False) if previous is not None else {}
    stored = {name: value for name, value in stored.items() if value is not None} | dict(values)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(f"{name}={_quoted(value)}\n" for name, value in sorted(stored.items()))
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

    def undo() -> None:
        if previous is None:
            path.unlink(missing_ok=True)
            return
        restored = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        descriptor = os.open(restored, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(previous)
        os.replace(restored, path)

    return undo
