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
"""A minimal bundle and its layered profiles a person completes, then loads like any other."""

from __future__ import annotations

import errno
import json
import os
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

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
# examples/agent_configs has more options. The application home (per platform, or
# ALPHAAVATAR_HOME) holds this file, so do not set application.home here.

avatar:
  id: {avatar_id}
  name: Assistant
  introduction: You are a helpful voice AI assistant.

profiles:
{profiles}
"""

_PROFILE = """\
# AlphaAvatar {section} profile, created by `alphaavatar config init`. Bundles reference it as
# {reference}. Never write credentials here; the bundle lists the environment it needs.

{body}"""

# The minimal template's selections and defaults, one section per profile, by layer.
# Switches shown are the defaults, written out to be edited; `alphaavatar setup` starts from
# them and replaces the sections its choices change.
SECTIONS = {
    "host": """\
rtc:
  backend: livekit  # Session transport; LIVEKIT_* in the environment hold its credentials.
health:
  bind: 127.0.0.1  # Readiness endpoint; 0.0.0.0 would expose it to the network.
log:
  file: true  # Diagnostic log files in the workspace's .logs/host.
doctor:
  external_services: false  # true: doctor may call the model, speech and other paid services.
""",
    "runtime": """\
inference:
  methods: {}  # Per runner, for example alphaavatar.voice.vad.silero: {workers: 2}
""",
    "context": """\
plugin: default
init_config:
    max_pending_preparations: 16
""",
    "loop": """\
plugin: realtime
init_config:
  model:
    backend: openai
    provider: openai
    model: gpt-5.6-luna
""",
    "voice": """\
vad:
  plugin: silero
stt:
  plugin: openai_segment
  model: gpt-4o-transcribe
tts:
  plugin: openai
  model: gpt-4o-mini-tts
  speaker: ash
""",
    "vision": """\
enabled: true  # Camera frames reach the loop's model as images; false keeps the Avatar blind.
""",
    "status": """\
plugin: default
enabled: true  # Intermediate status events, such as searching, sent to the client.
""",
    "router": """\
plugin: default
init_config:
  audio_activity:
    enabled: true
  addressing:
    semantic:
      enabled: true
      avatar_identities: [AlphaAvatar]  # Names people use to address the Avatar.
    visual:
      enabled: true
  turn_taking:
    enabled: true
    interruption:
      enabled: true
""",
    "character": """\
plugin: null  # airi shows a virtual character; see the character plugin's README to install.
""",
    "memory": """\
vdb_config:
  collection_name: memory
  embedding: {provider: openai, model: text-embedding-3-small}
init_config:
  conversation:
    provider:
      gateway:
        tasks:
          memory.conversation_delta: {provider: openai, model: gpt-4o, temperature: 0.1}
  tool:
    provider:
      gateway:
        tasks:
          memory.tool_delta: {provider: openai, model: gpt-4o, temperature: 0.1}
  environment:
    enabled: false  # ENV memory; enabling it also needs provider.task and its gateway task.
""",
    "persona": """\
vdb_config:
  profiler_collection_name: persona_profiler
  speaker_collection_name: persona_speaker
  face_collection_name: persona_face
  embedding: {provider: openai, model: text-embedding-3-small}
init_config:
  profiler:
    enabled: true
    provider:
      gateway:
        tasks:
          persona.profile_delta: {provider: openai, model: gpt-4o, temperature: 0.1}
  speaker:
    enabled: true  # Who is speaking, from voice; stored in speaker_collection_name.
    inference_queue_size: 1
  face:
    enabled: true  # Who is present, from video frames; stored in face_collection_name.
""",
    "tools": """\
deepresearch:
  plugin: null  # Tavily research reads TAVILY_API_KEY when enabled.
rag:
  plugin: null
mcp:
  enabled: false
  # Reference credentials with <ENV_VAR> placeholders; they resolve when the file loads:
  # servers:
  #   docs:
  #     url: https://example.com/mcp
  #     headers:
  #       Authorization: Bearer <MCP_DOCS_TOKEN>
""",
}


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
    from alphaavatar.host.application.config import HostConfig

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
