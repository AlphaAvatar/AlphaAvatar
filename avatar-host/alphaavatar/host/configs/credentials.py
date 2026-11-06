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

They live in a private file in the application home's settings, the one the settings name
(``credentials``), read into the environment by the commands that load a configuration,
after the .env file and never over a variable already set. Storing writes a new file beside
it, which the settings replacement that makes the bundle the default then names: the
default and the credentials it reads commit together, and a run killed before that leaves
the settings, and so every bundle, reading what they read. Values are never printed, logged
or written elsewhere.
"""

from __future__ import annotations

import contextlib
import os
import re
import secrets
from collections.abc import Mapping, Sequence
from pathlib import Path

from alphaavatar.host.workspace import ApplicationPaths

NAME = re.compile(r"[A-Z][A-Z0-9_]*")
FILE = re.compile(r"credentials-[0-9a-f]{16}\.env")


def _quoted(value: str) -> str:
    # Double quotes, with the backslash escapes python-dotenv reads back.
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def credentials_path(paths: ApplicationPaths) -> Path | None:
    """The stored credentials the settings name, if they name any."""
    from .bundles import ConfigReferenceError, read_settings

    name = read_settings(paths).get("credentials")
    if name is None:
        return None
    if not (isinstance(name, str) and FILE.fullmatch(name)):
        raise ConfigReferenceError(
            f"credentials in {paths.settings_file} is not a file setup stored"
        )
    return paths.settings_dir / name


def stored_credentials(paths: ApplicationPaths) -> dict[str, str]:
    from dotenv import dotenv_values

    path = credentials_path(paths)
    if path is None or not path.is_file():
        return {}
    stored = dotenv_values(path, interpolate=False).items()
    return {name: value for name, value in stored if value is not None}


def load_credentials(paths: ApplicationPaths) -> tuple[str, ...]:
    """Set each stored credential the environment lacks; the names set.

    Unreadable settings name none: a named bundle still loads, as it does without them, and
    Doctor's home check says what to fix. Setup refuses such settings before it stores any.
    """
    from .bundles import ConfigReferenceError

    try:
        stored = stored_credentials(paths)
    except ConfigReferenceError:
        return ()
    loaded = []
    for name, value in stored.items():
        if name not in os.environ:
            os.environ[name] = value
            loaded.append(name)
    return tuple(loaded)


def load_environment(overrides: Sequence[str] = ()) -> None:
    """The .env file start reads (ENV_FILE), then the credentials stored for the home."""
    from alphaavatar.agents.env import init_env

    from .bundles import application_paths

    init_env()  # It may set ALPHAAVATAR_HOME, which chooses the home.
    load_credentials(application_paths(overrides))


def write_credentials(paths: ApplicationPaths, values: Mapping[str, str]) -> Path:
    """The stored credentials merged with values, in a new private file nothing names yet.

    Other stored names keep their values. Call it under the settings lock, then name the
    file in the settings replacement, or remove it.
    """
    for name, value in values.items():
        if not NAME.fullmatch(name) or not isinstance(value, str) or not value:
            raise ValueError(f"Invalid credential {name}")
        if any(character in value for character in "\r\n\x00"):
            raise ValueError(f"{name} holds a line break")
    stored = stored_credentials(paths) | dict(values)
    text = "".join(f"{name}={_quoted(value)}\n" for name, value in sorted(stored.items()))
    path = paths.settings_dir / f"credentials-{secrets.token_hex(8)}.env"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def prune_credentials(paths: ApplicationPaths) -> None:
    """Remove the stored credential files the settings no longer name: replaced ones, and
    those a killed run wrote. Call it under the settings lock."""
    named = credentials_path(paths)
    for path in paths.settings_dir.glob("credentials-*.env"):
        if FILE.fullmatch(path.name) and path != named:
            with contextlib.suppress(OSError):
                path.unlink()
