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
after the .env file and never over a value already set: an empty or blank one counts as
unset there, as it does anywhere a credential is read. Storing writes a new file beside
it, which the settings replacement that makes the bundle the default then names: the
default and the credentials it reads commit together, and a run killed before that leaves
the settings, and so every bundle, reading what they read. Values are never printed, logged
or written elsewhere.
"""

from __future__ import annotations

import contextlib
import io
import os
import re
import secrets
from collections.abc import Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from alphaavatar.host.workspace import ApplicationPaths

if TYPE_CHECKING:
    from .bundles import Settings

NAME = re.compile(r"[A-Z][A-Z0-9_]*")
FILE = re.compile(r"credentials-[0-9a-f]{16}\.env")
CREDENTIAL_WORDS = frozenset({"KEY", "APIKEY", "SECRET", "TOKEN", "PASSWORD", "PAT", "URL"})


def _quoted(value: str) -> str:
    # Double quotes, with the backslash escapes python-dotenv reads back.
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _named(paths: ApplicationPaths, settings: Mapping[str, Any]) -> Path | None:
    from .bundles import ConfigReferenceError

    name = settings.get("credentials")
    if name is None:
        return None
    if not (isinstance(name, str) and FILE.fullmatch(name)):
        raise ConfigReferenceError(
            f"credentials in {paths.settings_file} is not a file setup stored"
        )
    return paths.settings_dir / name


def credentials_path(paths: ApplicationPaths) -> Path | None:
    """The stored credentials the settings name, if they name any."""
    from .bundles import read_settings

    return _named(paths, read_settings(paths))


def read_stored(paths: ApplicationPaths) -> Settings:
    """The settings and the stored credentials they name, as of one moment.

    A stored file is written whole before the settings name it, never changed, and removed
    only once they name another: one gone since the settings were read means they changed,
    so they are read again; named again, it is missing. A file opened reads whole even if it
    is removed meanwhile.
    """
    from dotenv import dotenv_values

    from .bundles import ConfigReferenceError, Settings, read_regular, read_settings

    missing: Path | None = None
    for _ in range(16):
        path: Path | None = None
        try:
            settings = read_settings(paths)
            path = _named(paths, settings)
            if path is None:
                return Settings(settings)
            text = read_regular(path)
        except FileNotFoundError:
            if path == missing:
                gone = ConfigReferenceError(f"Stored credentials are missing: {path}")
                return Settings(error=gone)
            missing = path
            continue
        except ConfigReferenceError as error:
            return Settings(error=error)
        except (OSError, UnicodeDecodeError):
            return Settings(
                error=ConfigReferenceError(f"Stored credentials cannot be read: {path}")
            )
        stored = dotenv_values(stream=io.StringIO(text), interpolate=False)
        values = {name: value for name, value in stored.items() if value is not None}
        return Settings(settings, values)
    changing = ConfigReferenceError(f"Settings in {paths.settings_dir} kept changing while read")
    return Settings(error=changing)


def stored_credentials(paths: ApplicationPaths) -> dict[str, str]:
    """The stored credentials, refusing settings that cannot be read."""
    settings = read_stored(paths)
    settings.checked()
    return dict(settings.credentials)


def fill_credentials(environ: MutableMapping[str, str], values: Mapping[str, str | None]) -> None:
    """Set each of ``values`` that holds a value where ``environ`` holds none. Unset, empty or
    only whitespace is none: it gives way to the next source and never displaces one, and a
    value is set as it is."""
    from alphaavatar.agents.utils import credential

    for name in values:
        if credential(name, environ) is None and (value := credential(name, values)) is not None:
            environ[name] = value


def load_credentials(paths: ApplicationPaths) -> Settings:
    """Set each stored credential the environment holds no value for, from one read of the
    settings, which is returned: the default bundle is chosen from it too.

    Settings that cannot be read name none: a named bundle still loads, as it does without
    them, and Doctor's home check says what to fix. Choosing the default, and setup, refuse
    them.
    """
    settings = read_stored(paths)
    fill_credentials(os.environ, settings.credentials)
    return settings


def _credential_name(name: str) -> bool:
    # A credential's name, or its server URL's, by its words, or one of AlphaAvatar's own.
    words = name.upper().split("_")
    return words[0] == "ALPHAAVATAR" or not CREDENTIAL_WORDS.isdisjoint(words)


def load_env_file() -> None:
    """Load the .env file ``ENV_FILE`` names (default ``.env``) as python-dotenv does: a
    variable the environment sets stays, empty too, and ``${NAME}`` reads the environment
    first. But a credential or an AlphaAvatar variable set empty or blank holds nothing: the
    file's value stands in for it, in references too, and an empty line sets none of them.
    A missing file sets nothing."""
    from dotenv import load_dotenv

    from alphaavatar.agents.utils import credential

    blank = {
        name: value
        for name, value in os.environ.items()
        if _credential_name(name) and credential(name) is None
    }
    for name in blank:  # Unset while the file loads, as python-dotenv then reads them.
        del os.environ[name]
    before = set(os.environ)
    try:
        load_dotenv(os.environ.get("ENV_FILE", ".env"))
    finally:
        for name in set(os.environ) - before:
            if _credential_name(name) and credential(name) is None:
                del os.environ[name]
        for name, value in blank.items():
            os.environ.setdefault(name, value)


def load_environment(overrides: Sequence[str] = ()) -> Settings:
    """The .env file start reads (ENV_FILE), then the credentials stored for the home; the
    settings read, to choose the default bundle from."""
    from .bundles import application_paths

    load_env_file()  # It may set ALPHAAVATAR_HOME, which chooses the home.
    return load_credentials(application_paths(overrides))


def write_credentials(paths: ApplicationPaths, values: Mapping[str, str]) -> Path:
    """The stored credentials merged with values, in a new private file nothing names yet.

    Other stored names keep their values. Call it under the settings lock, then name the
    file in the settings replacement, or remove it.
    """
    for name, value in values.items():
        if not NAME.fullmatch(name) or not isinstance(value, str) or not value.strip():
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
