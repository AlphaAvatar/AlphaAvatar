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
unset there, as it does anywhere a credential is read. Which variables are credentials the
configuration says (``configured_credentials``), with the ones components read when it names
none (``DEFAULT_CREDENTIALS``) and those stored. Storing writes a new file beside
it, which the settings replacement that makes the bundle the default then names: the
default and the credentials it reads commit together, and a run killed before that leaves
the settings, and so every bundle, reading what they read. Values are never printed, logged
or written elsewhere.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import secrets
from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from alphaavatar.host.workspace import ApplicationPaths

if TYPE_CHECKING:
    from .bundles import Settings

NAME = re.compile(r"[A-Z][A-Z0-9_]*")
FILE = re.compile(r"credentials-[0-9a-f]{16}\.env")
# The .env file's values a command read, as JSON, for the commands it runs to read instead of a
# file: upgrade's target runs from /, where a relative ENV_FILE names another or none.
FILE_VALUES = "ALPHAAVATAR_ENV_FILE_VALUES"
_OC_ENV = re.compile(r"\$\{oc\.env:\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)")
# What components read a credential from when the configuration names no variable of its own
# for it, as .env.template lists them.
DEFAULT_CREDENTIALS = (
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "VOICEAI_API_KEY",
    "TAVILY_API_KEY",
    "QDRANT_URL",
    "QDRANT_API_KEY",
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
)


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


def fill_credentials(
    environ: MutableMapping[str, str], names: Iterable[str], *sources: Mapping[str, str | None]
) -> None:
    """Set each of ``names`` that ``environ`` holds no value for to the first value of
    ``sources`` that holds one. Unset, empty or only whitespace is none, there as in each
    source: it gives way to the next and never displaces one, and a value is set as it is."""
    from alphaavatar.agents.utils import credential

    for name in names:
        if credential(name, environ) is None:
            for source in sources:
                if (value := credential(name, source)) is not None:
                    environ[name] = value
                    break


def _hide(names: Iterable[str]) -> None:
    from alphaavatar.agents.utils.env_utils import SERVER_KEY
    from alphaavatar.core.log.records import hide_variables

    # Their names need not say they hold one: a server's key, one a configuration names.
    hide_variables({*names, *(name for name in os.environ if name.startswith(SERVER_KEY))})


def load_credentials(paths: ApplicationPaths, file: Mapping[str, str] | None = None) -> Settings:
    """Fill the default credentials and the stored ones the environment holds no value for,
    from the .env file's values (``file``), then from one read of the stored ones. The read is
    returned with the file's values: the default bundle is chosen from it, and the credentials
    a configuration names are filled from both (``fill_configured``).

    Settings that cannot be read name none: a named bundle still loads, as it does without
    them, and Doctor's home check says what to fix. Choosing the default, and setup, refuse
    them.
    """
    settings = replace(read_stored(paths), file=dict(file or {}))
    names = (*DEFAULT_CREDENTIALS, *settings.credentials)
    fill_credentials(os.environ, names, settings.file, settings.credentials)
    _hide(())
    return settings


def configured_credentials(data: Mapping[str, Any]) -> set[str]:
    """The variables a composed configuration, as written, reads credentials from by name: each
    ``api_key_env`` it holds, wherever, and in its MCP servers the ``<NAME>`` placeholders and
    the ``${oc.env:NAME}`` interpolations, which once resolved no longer say where they read.
    An interpolation anywhere else reads an ordinary variable."""
    from alphaavatar.agents.utils.env_utils import ENV_PATTERN

    names: set[str] = set()

    def walk(value: Any, servers: bool) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if key == "api_key_env" and isinstance(item, str):
                    names.add(item)
                walk(item, servers)
        elif isinstance(value, list):
            for item in value:
                walk(item, servers)
        elif servers and isinstance(value, str):
            names.update(ENV_PATTERN.findall(value), _OC_ENV.findall(value))

    walk(data, False)
    tools = data.get("tools")
    mcp = tools.get("mcp") if isinstance(tools, Mapping) else None
    walk(mcp.get("servers") if isinstance(mcp, Mapping) else None, True)
    return names


def fill_configured(data: Mapping[str, Any], settings: Settings) -> None:
    """Fill the credentials a composed configuration names that the environment holds no
    value for, from the .env file, then the stored ones, as ``load_credentials`` read them;
    and hide their values from logs. Before it is interpolated: ``${oc.env:NAME}`` then reads
    the value filled, as its placeholders do when it is validated."""
    names = configured_credentials(data)
    fill_credentials(os.environ, names, settings.file, settings.credentials)
    _hide(names)


def load_env_file() -> dict[str, str]:
    """Load the .env file ``ENV_FILE`` names (default ``.env``) as python-dotenv loads it, parsed
    once: a variable the environment sets stays, empty too, and ``${NAME}`` reads the
    environment as it was first. Its values are returned, for credentials to be filled from;
    ALPHAAVATAR_HOME, which chooses the home that stores them, is filled here: an empty or blank
    one takes the file's. A missing file sets nothing. Given the values another command read
    (``FILE_VALUES``), they load in its place, and no file is read."""
    from dotenv.main import DotEnv, _load_dotenv_disabled

    if (given := os.environ.get(FILE_VALUES)) is not None:
        values = json.loads(given)
    elif _load_dotenv_disabled():  # PYTHON_DOTENV_DISABLED, as load_dotenv reads it.
        values = {}
    else:
        dotenv = DotEnv(os.environ.get("ENV_FILE", ".env"), encoding="utf-8", override=False)
        values = {name: value for name, value in dotenv.dict().items() if value is not None}
    for name, value in values.items():
        os.environ.setdefault(name, value)  # As load_dotenv sets them: one set stays, empty too.
    fill_credentials(os.environ, ("ALPHAAVATAR_HOME",), values)
    return values


def load_environment(overrides: Sequence[str] = ()) -> Settings:
    """The .env file start reads (ENV_FILE), then the credentials stored for the home; the
    settings read, to choose the default bundle from, with the file's values."""
    from .bundles import application_paths

    file = load_env_file()  # It may set ALPHAAVATAR_HOME, which chooses the home.
    return load_credentials(application_paths(overrides), file)


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
