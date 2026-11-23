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
"""The default bundle and its layered profiles, which a person edits, then loads like any other.

The profiles are the reference configuration (``examples/agent_configs/roles/demo.yaml``) with
every public setting written out, its schema's default where the reference names none, and
no tool on; they ship in this package as files, one per profile, comments and all.
"""

from __future__ import annotations

import errno
import json
import os
import re
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alphaavatar.host.workspace import ApplicationPaths

from .bundles import (
    LAYERS,
    ConfigReferenceError,
    bundle_path,
    check_bundle_name,
    check_inside,
    read_settings,
)

# Credentials stay in the environment (or the .env file named by ENV_FILE), never in the files.
REQUIRED_ENVIRONMENT = (
    ("OPENAI_API_KEY", "model, speech, embedding and memory/persona providers"),
    ("GOOGLE_API_KEY", "ENV memory (memory.init_config.environment), from Google's Gemini"),
    ("LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET", "session transport (host.rtc)"),
)

_BUNDLE = """\
# AlphaAvatar bundle {name}, created by `alphaavatar config init`.
# Never write credentials here. Before `alphaavatar start`, set in the environment or .env:
{environment}
#   start:                    alphaavatar dev {name}
#   check without starting:   alphaavatar config check {name}
# Each profiles entry is configs/profiles/<entry>.yaml in this application home and may be
# shared by several bundles: host, agent runtime, and plugins by layer (foundation,
# perception, tools). The Avatar identity belongs in this file.
# The application home (per platform, or ALPHAAVATAR_HOME) holds this file, so do not set
# application.home here.

avatar:
  id: {avatar_id}
  name: AlphaAvatar
  timezone: null  # IANA zone the Avatar tells times in, such as Asia/Shanghai; null: none set

  introduction: >
    You are AlphaAvatar, a real-time multimodal personal assistant. You can listen,
    see and speak with the people you help, remember what matters to each of them
    across conversations, and recognize them when they return. Be genuinely useful
    in everyday life: answer questions, help people think things through, and notice
    what is happening around you when it is relevant. Be honest about what you know
    and what you are unsure of, and keep what each person shares with you private to them.

profiles:
{profiles}
"""

_PROFILE = """\
# AlphaAvatar {section} profile, created by `alphaavatar config init`. Bundles reference it as
# {reference}. Every setting is written out; edit any, then `alphaavatar config check`.
# Never write credentials here; the bundle lists the environment it needs.

{body}"""

TEMPLATES = Path(__file__).with_name("templates")


def _template(section: str) -> Path:
    """Where a section's default profile ships: the plugins' by their layer, the rest on top."""
    layer = LAYERS[section]
    return TEMPLATES / (layer if layer.startswith("plugins/") else "") / f"{section}.yaml"


# The default profiles, one section each, by layer; `alphaavatar setup` starts from them and
# changes the settings its choices change, in place.
SECTIONS = {section: _template(section).read_text("utf-8") for section in LAYERS}

# A setting's line in a profile: its indentation, key, and what follows the colon.
_SETTING = re.compile(r"^( *)([A-Za-z0-9_.\-]+):(?=\s|$)(.*)$")


def _setting(line: str) -> tuple[int, str, str] | None:
    found = _SETTING.match(line)
    return (len(found[1]), found[2], found[3]) if found else None


def _end(lines: list[str], index: int) -> int:
    """Where the setting on ``index`` ends: after its last more indented line, blank lines and
    comments that follow it not included."""
    indent, end = _setting(lines[index])[0], index + 1
    for at in range(index + 1, len(lines)):
        line = lines[at]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if len(line) - len(line.lstrip(" ")) <= indent:
            break
        end = at + 1
    return end


def _find(lines: list[str], path: Sequence[str]) -> int | None:
    start, stop, indent, found = 0, len(lines), 0, None
    for key in path:
        found, at = None, start
        while at < stop:
            setting = _setting(lines[at])
            if setting is not None and setting[0] == indent:
                if setting[1] == key:
                    found = at
                    break
                at = _end(lines, at)
                continue
            at += 1
        if found is None:
            return None
        start, stop, indent = found + 1, _end(lines, found), indent + 2
    return found


def _scalar(value: Any) -> str:
    import yaml

    return yaml.safe_dump(value, default_flow_style=True, width=1 << 20).split("\n...")[0].strip()


def _lines(key: str, value: Any, indent: int, comment: str) -> list[str]:
    """A setting as the profiles write one: a mapping as a block, anything else on its line."""
    if isinstance(value, dict) and value:
        children = [line for k, v in value.items() for line in _lines(k, v, indent + 2, "")]
        return [f"{' ' * indent}{key}:{comment}", *children]
    return [f"{' ' * indent}{key}: {_scalar(value)}{comment}"]


@dataclass(frozen=True, slots=True)
class Change:
    """A setting a choice changes in a default profile, where it is; one the profile lacks is
    added under its parent, after the sibling ``after`` names. ``note`` replaces its comment."""

    path: tuple[str, ...]
    value: Any
    note: str | None = None
    after: str | None = None


def change_profile(text: str, changes: Sequence[Change]) -> str:
    """The profile with each change made where its setting is: every other line, comment and
    blank line as it was. The result is checked against the same changes made to its data."""
    import yaml

    lines = text.splitlines()
    for change in changes:
        *parents, key = change.path
        at = _find(lines, change.path)
        if at is not None:
            indent, _, rest = _setting(lines[at])
            comment = re.search(r"\s+#.*$", rest)
            kept = f"  # {change.note}" if change.note else (comment[0] if comment else "")
            lines[at : _end(lines, at)] = _lines(key, change.value, indent, kept)
            continue
        parent = _find(lines, parents)
        if parent is None:
            raise KeyError(f"No setting {'.'.join(parents)} to add {key} under")
        sibling = _find(lines, (*parents, change.after)) if change.after else None
        where = _end(lines, sibling if sibling is not None else parent)
        note = f"  # {change.note}" if change.note else ""
        lines[where:where] = _lines(key, change.value, len(parents) * 2, note)
    result = "\n".join(lines) + "\n"
    expected = yaml.safe_load(text)
    for change in changes:
        *parents, key = change.path
        target = expected
        for part in parents:
            target = target[part]
        target[key] = change.value
    if yaml.safe_load(result) != expected:
        raise ValueError(f"Changing {[c.path for c in changes]} would not keep the profile intact")
    return result


@dataclass(frozen=True, slots=True)
class CreatedBundle:
    name: str
    bundle: Path
    profiles: tuple[Path, ...]
    default_bundle: str  # The default after creation: this bundle, or the one kept.


def render_bundle(
    name: str,
    avatar_id: str,
    *,
    sections: Mapping[str, str] | None = None,
    environment: Sequence[tuple[str, str]] = REQUIRED_ENVIRONMENT,
) -> dict[str, str]:
    """Bundle and profile texts by path under ``configs``, validated before any file exists.

    ``sections`` replace the template's bodies of those sections; ``environment`` lists the
    variables the bundle's header names.
    """
    import yaml

    from alphaavatar.agents.configs import AvatarConfig
    from alphaavatar.host.service.application.config import HostConfig

    check_bundle_name(name)
    bodies = SECTIONS | dict(sections or {})
    if set(bodies) != set(SECTIONS):
        raise ValueError(f"Unknown sections: {', '.join(sorted(set(bodies) - set(SECTIONS)))}")
    names = {section: f"{name}/{LAYERS[section]}/{section}" for section in bodies}
    # Validate the identifier itself: YAML would fold line breaks such as U+0085 into spaces.
    AvatarConfig.model_validate({"avatar": {"id": avatar_id}})
    texts = {
        f"bundles/{name}.yaml": _BUNDLE.format(
            name=name,
            # A JSON string is a valid double-quoted YAML scalar for any accepted identifier.
            avatar_id=json.dumps(avatar_id, ensure_ascii=False),
            environment="\n".join(f"#   {key:<50} {use}" for key, use in environment),
            profiles="\n".join(f"  {section}: {reference}" for section, reference in names.items()),
        )
    }
    texts |= {
        f"profiles/{names[section]}.yaml": _PROFILE.format(
            section=section, reference=names[section], body=body
        )
        for section, body in bodies.items()
    }
    bundle = yaml.safe_load(texts[f"bundles/{name}.yaml"])
    bundle |= {section: yaml.safe_load(body) for section, body in bodies.items()}
    HostConfig.model_validate(bundle.pop("host"))
    rendered = AvatarConfig.model_validate({k: v for k, v in bundle.items() if k != "profiles"})
    if rendered.avatar.id != avatar_id:
        raise ValueError("The Avatar ID would not survive the configuration file unchanged")
    return texts


def _directory(path: Path, created: list[Path]) -> None:
    missing = []
    while not path.exists():
        missing.append(path)
        path = path.parent
    for directory in reversed(missing):
        directory.mkdir()
        created.append(directory)


def _set_default(
    paths: ApplicationPaths,
    name: str,
    created: list[Path],
    staged: list[Path],
    replace: bool,
    credentials: Mapping[str, str] | None = None,
) -> str:
    """Set the default, unless one is set and not ``replace``; replacing the file commits it
    and the stored credentials, with ``credentials`` merged in, together."""
    import yaml

    from alphaavatar.agents.utils.files.atomic import locked_directory

    from .credentials import prune_credentials, write_credentials

    if (default := read_settings(paths).get("default_bundle")) is not None and not replace:
        return default
    target = paths.settings_file
    _directory(target.parent, created)
    lock = target.parent / ".write.lock"
    if lock.is_symlink():
        # Opening the lock truncates whatever a linked lock file points to.
        raise ConfigReferenceError(f"Refusing to lock settings through a symbolic link: {lock}")
    # Read, decide and replace under one lock: concurrent inits never both become default.
    with locked_directory(target.parent):
        settings = read_settings(paths)
        if (default := settings.get("default_bundle")) is not None and not replace:
            return default
        try:
            text, mode = target.read_text(encoding="utf-8"), target.stat().st_mode
        except FileNotFoundError:
            text, mode = "", None
        changes = {"default_bundle": name}
        if credentials:
            stored = write_credentials(paths, credentials)
            created.append(stored)  # Named by the replacement below, or removed.
            changes["credentials"] = stored.name
        expected = settings | changes
        # Appending keeps every other setting and its comments, when the result still holds
        # the same values; otherwise the values are written again without comments.
        text += "\n" if text and not text.endswith("\n") else ""
        text += "".join(f"{key}: {value}\n" for key, value in changes.items())
        try:
            appended = not changes.keys() & settings.keys() and yaml.safe_load(text) == expected
        except yaml.YAMLError:
            appended = False
        if not appended:
            text = yaml.safe_dump(expected, sort_keys=False, allow_unicode=True)
        temporary = target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp")
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            staged.append(temporary)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            temporary.chmod(mode)
        os.replace(temporary, target)
        if credentials:
            prune_credentials(paths)  # Those it replaced, and any a killed run wrote.
    return name


def set_default_bundle(paths: ApplicationPaths, name: str) -> None:
    """Make an existing bundle the default: one replacement of the settings, under their lock.
    Before it commits, a failure leaves the settings as they were."""
    path = bundle_path(paths, name)
    if not path.is_file():
        raise ConfigReferenceError(f"Bundle {name!r} does not exist: {path}")
    created: list[Path] = []
    staged: list[Path] = []
    try:
        _set_default(paths, name, created, staged, True)
    except BaseException:
        for temporary in staged:
            temporary.unlink(missing_ok=True)  # Gone once the replacement committed.
        raise


def create_bundle(
    paths: ApplicationPaths,
    name: str,
    *,
    avatar_id: str,
    sections: Mapping[str, str] | None = None,
    environment: Sequence[tuple[str, str]] = REQUIRED_ENVIRONMENT,
    make_default: bool = False,
    credentials: Mapping[str, str] | None = None,
) -> CreatedBundle:
    """Create the bundle and its profiles, then the default; never overwrite existing files.

    ``credentials`` are stored with the default it becomes (``make_default``): one settings
    replacement commits both.

    The bundle becomes the default when none is set, or always with ``make_default``. Every target stays inside the real application home. Until the settings replacement
    commits, a failure or cancellation removes only the files and empty directories this
    call created; existing files, shared profiles and settings stay as they were. After it,
    the complete bundle stays and the failure propagates.
    """
    if credentials and not make_default:
        raise ValueError("Credentials are stored with the default they belong to")
    texts = render_bundle(name, avatar_id, sections=sections, environment=environment)
    read_settings(paths)  # Unreadable settings refuse before any file exists.
    targets = {paths.configs.root / relative: text for relative, text in texts.items()}
    bundle, *profiles = targets
    # The same directories that loading accepts: a created bundle always loads.
    for target, directory in (
        (bundle, paths.configs.bundles_dir),
        *((profile, paths.configs.profiles_dir) for profile in profiles),
        (paths.settings_file, paths.settings_dir),
    ):
        check_inside(paths, target, directory, "Refusing to create")
    for target in targets:
        if target.exists():
            raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), str(target))
    created: list[Path] = []
    staged: list[Path] = []  # The settings replacement: once it is gone, it committed.
    try:
        for target, text in targets.items():
            _directory(target.parent, created)
            with target.open("x", encoding="utf-8", newline="\n") as stream:
                created.append(target)
                stream.write(text)
        default = _set_default(paths, name, created, staged, make_default, credentials)
    except BaseException:
        if not staged or staged[0].exists():
            for path in reversed([*created, *staged]):
                try:
                    path.rmdir() if path.is_dir() else path.unlink()
                except OSError:
                    continue  # Not empty or already gone: someone else's content stays.
        raise
    return CreatedBundle(name, bundle, tuple(profiles), default)
