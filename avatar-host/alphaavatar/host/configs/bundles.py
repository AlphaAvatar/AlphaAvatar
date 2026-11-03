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
"""Named bundles, the plugin profiles they reference, and the default bundle setting.

A bundle is an application configuration stored as ``configs/bundles/<name>.yaml`` in the
application home. Its ``profiles`` mapping places one profile under each plugin section::

    profiles:
      voice: my-avatar/voice  # configs/profiles/my-avatar/voice.yaml

A profile is one section body and references nothing, so references cannot form a cycle.
A section comes from the configuration file or from one profile, never both. Names use a
fixed alphabet and are never paths, and their real locations, symbolic links resolved, stay
in their directory of the application home; explicit configuration files keep their own path
rules. Reading is pure: it creates no directory and changes no setting or environment
variable.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alphaavatar.core.log.diagnostics import format_error
from alphaavatar.core.log.records import Redactor
from alphaavatar.core.workspace import ApplicationPaths

from .paths import platform_application_root, resolve_application_paths

NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
PROFILE = re.compile(rf"{NAME.pattern}(?:/{NAME.pattern})*")
_NAMES = "1-64 lowercase letters, digits, '-' or '_', starting with a letter or digit"


class ConfigReferenceError(ValueError):
    """A selection or reference that cannot be resolved.

    Messages hold only fixed text, validated names, section keys and paths, never file
    contents, so they are safe to show.
    """


@dataclass(frozen=True, slots=True)
class ConfigSource:
    path: Path
    bundle: str | None = None
    default: bool = False  # Chosen through settings.default_bundle.
    home: Path | None = None  # A named bundle belongs to the home that stores it.

    @property
    def origin(self) -> str:
        return f"Bundle {self.bundle!r}" if self.bundle else f"Configuration {self.path}"


def format_failure(error: BaseException, *, details: bool = False) -> str:
    """``format_error``, except that a reference failure also shows its safe message."""
    if isinstance(error, ConfigReferenceError):
        # The Host log boundary still applies: environment secrets and control characters.
        return f"  error: {type(error).__name__}\n    {Redactor()(str(error), limit=None)}"
    return format_error(error, details=details)


def plugin_sections() -> frozenset[str]:
    """Sections a profile may fill: every Avatar plugin, not the Avatar or its runtime."""
    from alphaavatar.agents.configs import AvatarConfig

    return frozenset(AvatarConfig.model_fields) - {"avatar", "runtime"}


def check_bundle_name(name: str) -> str:
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ConfigReferenceError(f"Bundle names use {_NAMES}")
    return name


def bundle_path(paths: ApplicationPaths, name: str) -> Path:
    return paths.configs.bundles_dir / f"{check_bundle_name(name)}.yaml"


def profile_path(paths: ApplicationPaths, name: str) -> Path:
    *directories, leaf = name.split("/")
    return paths.configs.profiles_dir.joinpath(*directories, f"{leaf}.yaml")


def check_inside(paths: ApplicationPaths, path: Path, directory: Path, label: str) -> None:
    """A named file's real location stays in its directory, itself in the real home.

    Resolving both sides keeps a home reached through an alias valid.
    """
    real, boundary = path.resolve(), directory.resolve()
    if not (real.is_relative_to(boundary) and boundary.is_relative_to(paths.root.resolve())):
        raise ConfigReferenceError(f"{label}: {path} resolves outside {directory} to {real}")


def application_paths(overrides: Sequence[str] = ()) -> ApplicationPaths:
    """The home holding bundles and settings, chosen as for loading; settings never choose it."""
    from omegaconf import OmegaConf
    from omegaconf.errors import OmegaConfBaseException

    try:
        home = OmegaConf.select(OmegaConf.from_dotlist(list(overrides)), "application.home")
    except OmegaConfBaseException:
        raise ValueError("Invalid YAML, configuration override, or interpolation") from None
    return resolve_application_paths(
        os.environ, default_root=platform_application_root(os.environ, Path.home()), home=home
    )


def read_settings(paths: ApplicationPaths) -> dict[str, Any]:
    """User application settings; only ``default_bundle`` is interpreted here."""
    import yaml

    try:
        text = paths.settings_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    try:
        settings = yaml.safe_load(text)
    except yaml.YAMLError:
        raise ConfigReferenceError(f"Settings are not valid YAML: {paths.settings_file}") from None
    settings = {} if settings is None else settings
    if not isinstance(settings, dict) or not all(isinstance(key, str) for key in settings):
        raise ConfigReferenceError(f"Settings must be a mapping: {paths.settings_file}")
    default = settings.get("default_bundle")
    if default is not None and not (isinstance(default, str) and NAME.fullmatch(default)):
        raise ConfigReferenceError(
            f"default_bundle in {paths.settings_file} is not a bundle name; names use {_NAMES}"
        )
    return settings


def is_file_argument(target: str) -> bool:
    return any(separator in target for separator in {"/", os.sep, os.altsep} - {None}) or bool(
        Path(target).suffix
    )


def select_configuration(target: str | None, overrides: Sequence[str] = ()) -> ConfigSource:
    """A path-like argument is a file, any other is a bundle name, none is the default bundle.

    The spelling alone decides: a missing bundle never falls back to a file, nor the reverse.
    """
    if target is not None and is_file_argument(target):
        return ConfigSource(Path(target).expanduser().absolute())
    paths = application_paths(overrides)
    default = target is None
    if default:
        target = read_settings(paths).get("default_bundle")
        if target is None:
            raise ConfigReferenceError(
                f"No configuration given and no default bundle in {paths.settings_file}; "
                "pass a bundle name or a file, or create a bundle with "
                "`alphaavatar config init <name> --avatar-id <id>`"
            )
    path, label = bundle_path(paths, target), f"{'Default b' if default else 'B'}undle {target!r}"
    if not path.is_file():
        raise ConfigReferenceError(f"{label} does not exist: {path}")
    check_inside(paths, path, paths.configs.bundles_dir, label)
    return ConfigSource(path, target, default=default, home=paths.root)


def compose_profiles(
    document: dict[str, Any], paths: ApplicationPaths, origin: str
) -> dict[str, Any]:
    """Place each referenced profile under its section; the result has no ``profiles``."""
    import yaml

    references = document.pop("profiles", None)
    if references is None:
        return document
    sections = plugin_sections()
    if not isinstance(references, dict):
        raise ConfigReferenceError(f"{origin}: profiles must map plugin sections to profiles")
    for section, name in references.items():
        if section not in sections:
            raise ConfigReferenceError(
                f"{origin}: profiles may only fill {', '.join(sorted(sections))}"
            )
        where = f"profiles.{section}"
        if section in document:
            raise ConfigReferenceError(f"{origin}: {section} is set both inline and by {where}")
        if not isinstance(name, str) or not PROFILE.fullmatch(name):
            raise ConfigReferenceError(
                f"{origin}: {where} must be a profile name, <directory>/<name> with {_NAMES}"
            )
        path = profile_path(paths, name)
        if not path.is_file():
            raise ConfigReferenceError(
                f"{origin}: {where} references missing profile {name!r}: {path}"
            )
        check_inside(paths, path, paths.configs.profiles_dir, f"{origin}: {where}")
        try:
            body = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            # The parser error would quote the line, which may hold a credential.
            raise ConfigReferenceError(f"{origin}: profile {name!r} is not valid YAML") from None
        body = {} if body is None else body
        if not isinstance(body, dict):
            raise ConfigReferenceError(f"{origin}: profile {name!r} must be a mapping")
        if "profiles" in body:
            raise ConfigReferenceError(
                f"{origin}: profile {name!r} references profiles; only bundles do"
            )
        document[section] = body
    return document
