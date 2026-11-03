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
"""Doctor: static, read-only diagnosis of the installation and a selected configuration.

Selection, loading and the output boundary are the public services `config check`, `start`
and `dev` use. Nothing is created, downloaded, loaded, started or contacted, so models,
services and devices are reported as not verified, never as passing. The report is plain
data for the CLI, an App or a TUI.
"""

from __future__ import annotations

import os
import platform
import shutil
import socket
import stat
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from packaging.requirements import Requirement

    from alphaavatar.core.workspace import ApplicationPaths
    from alphaavatar.host.configs import ApplicationConfig, ConfigSource

Status = Literal["PASS", "WARN", "FAIL", "SKIP"]
STATUSES: tuple[Status, ...] = ("PASS", "WARN", "FAIL", "SKIP")
HOST = "alpha-avatar-host"
MIN_FREE_BYTES = 1 << 30  # Less leaves little room for models, caches and Avatar data.


@dataclass(frozen=True, slots=True)
class CheckSpec:
    id: str
    title: str
    needs_configuration: bool = False


# Stable identifiers, in report order.
CHECKS = (
    CheckSpec("system.platform", "Operating system and the POSIX local socket API"),
    CheckSpec("python.version", "Python interpreter against the versions AlphaAvatar supports"),
    CheckSpec("packages.alphaavatar", "AlphaAvatar packages: one release, Host requirements"),
    CheckSpec("config.load", "Selection, profiles, overrides and validation, as config check"),
    CheckSpec("config.runners", "Inference runners and workers the configuration selects", True),
    CheckSpec("packages.capabilities", "Packages the enabled capabilities need", True),
    CheckSpec("paths.home", "Application home and settings: state, permissions, free space"),
    CheckSpec("paths.cache", "Cache root: state, permissions, free space"),
    CheckSpec("paths.workspace", "Avatar workspace: state, permissions, free space", True),
    CheckSpec("models.runners", "Runner models: not loaded, so not verified", True),
    CheckSpec("services.external", "RTC, model, speech and tool services: not contacted", True),
    CheckSpec("devices.media", "Microphones and cameras: not opened"),
)


@dataclass(frozen=True, slots=True)
class Check:
    id: str
    status: Status
    summary: str
    details: tuple[str, ...] = ()
    action: str | None = None  # The next step, for anything but a pass.


@dataclass(frozen=True, slots=True)
class Report:
    checks: tuple[Check, ...]

    @property
    def status(self) -> Status:
        """FAIL if any check failed, else WARN if any warned; skipped checks never pass."""
        statuses = {check.status for check in self.checks}
        return "FAIL" if "FAIL" in statuses else "WARN" if "WARN" in statuses else "PASS"

    @property
    def exit_code(self) -> int:
        """1 when a check failed; 0 otherwise, warnings and unverified checks included."""
        return 1 if self.status == "FAIL" else 0

    def counts(self) -> dict[Status, int]:
        return {status: sum(check.status == status for check in self.checks) for status in STATUSES}

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "counts": self.counts(),
            "checks": [asdict(check) for check in self.checks],
        }


def diagnose(
    target: str | None = None,
    overrides: Sequence[str] = (),
    *,
    read_env: Callable[[], object] | None = None,
) -> Report:
    """Every check in ``CHECKS`` order; a check that cannot complete is reported as FAIL.

    ``target`` and ``overrides`` mean what they mean for ``config check``. ``read_env``, if
    given, loads the environment file first, as ``start`` does; its failure is reported.
    """
    from alphaavatar.host.configs import application_paths, output_scrubber

    loaded, load = _configuration(target, overrides, read_env)
    config = loaded[0] if loaded is not None else None
    checks = {
        "system.platform": _safely("system.platform", _platform),
        "python.version": _safely("python.version", _python),
        "packages.alphaavatar": _safely("packages.alphaavatar", _packages),
        "config.load": load,
        "devices.media": Check(
            "devices.media",
            "SKIP",
            "Not verified: Doctor opens no microphone or camera; the Host receives media "
            "from RTC participants",
            action="Join a dev session from a client to try its devices",
        ),
    }

    paths = None
    if load.summary != _UNREADABLE_ENV:  # Otherwise the home may be set in the unread file.
        try:
            paths = config.paths if config is not None else application_paths(overrides)
        except Exception:
            pass  # Loading resolves the home the same way: config.load reports why.
    if paths is not None:
        checks["paths.home"] = _safely("paths.home", lambda: _home(paths, overrides))
        checks["paths.cache"] = _safely("paths.cache", lambda: _cache(paths))
    if loaded is not None:
        config, source = loaded
        checks |= {
            "config.runners": _safely("config.runners", lambda: _runners(config)),
            "packages.capabilities": _safely(
                "packages.capabilities", lambda: _capabilities(config, source)
            ),
            "paths.workspace": _safely(
                "paths.workspace", lambda: _directory("paths.workspace", config.workspace.root)
            ),
            "models.runners": _safely("models.runners", lambda: _models(config, source)),
            "services.external": _safely("services.external", lambda: _services(config, source)),
        }
    # Without a configuration, config.load names the next step for every check that needs one.
    reason = "No configuration selected" if load.status == "WARN" else "Configuration not loaded"
    for spec in CHECKS:
        checks.setdefault(spec.id, Check(spec.id, "SKIP", f"{reason}; see config.load"))

    scrub = output_scrubber(config)
    return Report(
        tuple(
            Check(
                check.id,
                check.status,
                scrub(check.summary),
                tuple(scrub(line) for line in check.details),
                scrub(check.action) if check.action is not None else None,
            )
            for check in (checks[spec.id] for spec in CHECKS)
        )
    )


def _safely(check_id: str, run: Callable[[], Check]) -> Check:
    from alphaavatar.host.configs import format_failure

    try:
        return run()
    except Exception as error:
        return Check(
            check_id,
            "FAIL",
            "The check could not complete",
            tuple(line.strip() for line in format_failure(error).splitlines() if line.strip()),
            "Report this with the output of `alphaavatar doctor --json`",
        )


_UNREADABLE_ENV = "The environment file could not be read"


def _configuration(
    target: str | None, overrides: Sequence[str], read_env: Callable[[], object] | None
) -> tuple[tuple[ApplicationConfig, ConfigSource] | None, Check]:
    from alphaavatar.host.configs import (
        application_paths,
        check_application_paths,
        describe_summary,
        format_failure,
        load_application,
        read_settings,
        select_configuration,
    )

    def failure(summary: str, error: Exception, action: str) -> Check:
        lines = (line.strip() for line in format_failure(error).splitlines())
        return Check("config.load", "FAIL", summary, tuple(line for line in lines if line), action)

    if read_env is not None:
        try:
            read_env()
        except Exception as error:
            return None, failure(
                _UNREADABLE_ENV,
                error,
                "Fix the file ENV_FILE names (default .env): UTF-8 text of KEY=VALUE lines",
            )
    try:
        if target is None:
            paths = application_paths(overrides)
            if read_settings(paths).get("default_bundle") is None:
                return None, Check(
                    "config.load",
                    "WARN",
                    f"No configuration given and no default bundle in {paths.settings_file}",
                    action="Create one with `alphaavatar config init <name> --avatar-id <id>`, "
                    "or pass a bundle name or a configuration file",
                )
        source = select_configuration(target, overrides)
        config = load_application(source, overrides)
        check_application_paths(config)
        describe_summary(config, source)  # config check's remaining validation, discarded.
    except Exception as error:
        if isinstance(error, ModuleNotFoundError) and error.name:
            action = f"Install the package that provides the Python module {error.name!r}"
        else:
            action = "Fix the reported field or reference, then run doctor again"
        return None, failure("The configuration did not load", error, action)
    return (config, source), Check(
        "config.load",
        "PASS",
        f"{_origin(source)} loaded and validated",
        (f"avatar {config.avatar.avatar.id}",),
    )


def _origin(source: ConfigSource) -> str:
    if source.bundle is None:
        return f"file {source.path}"
    return f"bundle {source.bundle}" + (" (default)" if source.default else "")


def _platform() -> Check:
    system = " ".join(filter(None, (platform.system(), platform.release(), platform.machine())))
    if os.name != "posix" or not hasattr(socket, "AF_UNIX"):
        return Check(
            "system.platform",
            "FAIL",
            f"{system or sys.platform}: the Host needs the POSIX local socket API (AF_UNIX)",
            action="Run AlphaAvatar on Linux or macOS",
        )
    # Only the API is checked: opening a socket is left to start, as sandboxes may refuse it.
    return Check("system.platform", "PASS", f"{system}; AF_UNIX socket API present, not opened")


def _python() -> Check:
    from packaging.specifiers import SpecifierSet

    version, supported = platform.python_version(), metadata.metadata(HOST)["Requires-Python"]
    found = f"Python {version} ({platform.python_implementation()}) at {sys.executable}"
    if supported and not SpecifierSet(supported).contains(version, prereleases=True):
        return Check(
            "python.version",
            "FAIL",
            f"{found}; AlphaAvatar supports {supported}",
            action=f"Install AlphaAvatar into a Python {supported} environment",
        )
    return Check("python.version", "PASS", f"{found}; supported ({supported or 'any'})")


def _packages() -> Check:
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name

    releases: dict[str, list[str]] = {}
    for distribution in metadata.distributions():
        name = canonicalize_name(distribution.metadata["Name"] or "")
        if name.startswith("alpha-avatar-"):
            releases.setdefault(distribution.version, []).append(name)
    count = sum(map(len, releases.values()))
    problems = _unmet(Requirement(HOST), set())
    if problems:
        return Check(
            "packages.alphaavatar",
            "FAIL",
            "The Host's requirements are not all installed",
            tuple(problems),
            f"Install into this Python environment: '{HOST}'",
        )
    if len(releases) > 1:
        return Check(
            "packages.alphaavatar",
            "WARN",
            f"{count} AlphaAvatar packages from {len(releases)} releases",
            tuple(f"{version}: {', '.join(sorted(names))}" for version, names in releases.items()),
            "Install every AlphaAvatar package from the same release",
        )
    (release,) = releases
    return Check(
        "packages.alphaavatar",
        "PASS",
        f"{count} AlphaAvatar packages, release {release}; Host requirements installed",
    )


def _unmet(requirement: Requirement, seen: set[tuple[str, str]]) -> list[str]:
    """What is missing or mismatched; AlphaAvatar's own requirements are followed, once each."""
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name

    try:
        distribution = metadata.distribution(requirement.name)
    except metadata.PackageNotFoundError:
        return [f"{requirement.name} is not installed"]
    problems = []
    if not requirement.specifier.contains(distribution.version, prereleases=True):
        problems.append(
            f"{requirement.name} {distribution.version} is installed; "
            f"{requirement.specifier} is required"
        )
    name = canonicalize_name(requirement.name)
    if not name.startswith("alpha-avatar-"):
        return problems
    # "" stands for the base requirements; each extra adds its own.
    extras = [extra for extra in ("", *sorted(requirement.extras)) if (name, extra) not in seen]
    seen.update((name, extra) for extra in extras)
    for text in distribution.requires or ():
        child = Requirement(text)
        if child.marker is None:
            wanted = "" in extras
        else:
            wanted = any(child.marker.evaluate({"extra": extra}) for extra in extras)
        if wanted:
            problems += _unmet(child, seen)
    return problems


def _with_extra(distribution: str, name: str) -> str:
    """A distribution with the extra named after the selected plugin, if it has one."""
    try:
        extras = metadata.metadata(distribution).get_all("Provides-Extra") or []
    except metadata.PackageNotFoundError:
        return distribution  # Reported as not installed when checked.
    return f"{distribution}[{name}]" if name in extras else distribution


def _provider_backends(config: ApplicationConfig) -> tuple[set[str], list[str]]:
    """Backends the enabled plugins' provider tasks use, with their configuration defaults.

    Built-in plugins are validated with the schemas they use at start, so omitted fields take
    their defaults; disabled plugins are not read. Vector store embeddings always use the
    default backend. What cannot be determined statically is returned as unverified.
    """
    from pydantic import BaseModel

    from alphaavatar.agents.avatar.provider.schemas import ProviderTaskConfig

    avatar = config.avatar
    default = ProviderTaskConfig.model_fields["backend"].default
    backends: set[str] = set()
    unverified: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, ProviderTaskConfig):
            backends.add(value.backend)
        elif isinstance(value, BaseModel):
            for name in type(value).model_fields:
                collect(getattr(value, name))
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)
        elif isinstance(value, list | tuple):
            for item in value:
                collect(item)

    def validate(label: str, schema: Callable[[], type[BaseModel]], init_config: Any) -> None:
        from alphaavatar.host.configs import format_failure

        try:
            collect(schema().model_validate(init_config))
        except Exception as error:
            failure = "; ".join(line.strip() for line in format_failure(error).splitlines())
            unverified.append(f"{label} init_config: {failure}")

    def loop() -> type[BaseModel]:
        from alphaavatar.plugins.loop.config import RealtimeLoopConfig

        return RealtimeLoopConfig

    def memory() -> type[BaseModel]:
        from alphaavatar.plugins.memory.config import DefaultMemoryConfig

        return DefaultMemoryConfig

    def persona() -> type[BaseModel]:
        from alphaavatar.plugins.persona.config import DefaultPersonaConfig

        return DefaultPersonaConfig

    if avatar.loop.plugin == "realtime":
        validate("loop", loop, avatar.loop.init_config)
    else:
        unverified.append(f"loop plugin {avatar.loop.plugin!r}")
    for name, section, schema in (
        ("memory", avatar.memory, memory),
        ("persona", avatar.persona, persona),
    ):
        if section.plugin == "default":
            validate(name, schema, section.init_config)
            backends.add(default)  # Its vector store embeds with the default backend.
        else:
            unverified.append(f"{name} plugin {section.plugin!r}")
    mcp = avatar.tools.mcp
    if mcp.enabled and mcp.plugin is not None:
        if mcp.plugin == "default":
            backends.add(default)
        else:
            unverified.append(f"mcp plugin {mcp.plugin!r}")
    return backends, unverified


def _capabilities(config: ApplicationConfig, source: ConfigSource) -> Check:
    from packaging.requirements import Requirement

    avatar, host = config.avatar, config.host
    needs: dict[str, list[str]] = {}
    problems: list[str] = []

    def plugin(capability: str, group: str, name: str) -> None:
        matches = tuple(metadata.entry_points(group=group, name=name))
        if len(matches) == 1 and matches[0].dist is not None:
            needs.setdefault(capability, []).append(_with_extra(matches[0].dist.name, name))
        else:
            problems.append(f"{capability}: {len(matches)} installed {group} plugins {name!r}")

    needs["rtc"] = [_with_extra(HOST, host.rtc.backend)]
    plugin("loop", "alphaavatar.loop", avatar.loop.plugin)
    plugin("context", "alphaavatar.context", avatar.context.plugin)
    backends, unverified = _provider_backends(config)
    for backend in sorted(backends):
        plugin("providers", "alphaavatar.provider", backend)
    voice = avatar.voice
    if any(part.plugin is not None for part in (voice.vad, voice.stt, voice.tts)):
        needs["voice"] = ["alpha-avatar-plugins-voice"]
    needs["router"] = ["alpha-avatar-plugins-router"]
    if avatar.status.enabled:
        needs["status"] = ["alpha-avatar-plugins-status"]
    if avatar.character.plugin is not None:
        needs["character"] = ["alpha-avatar-plugins-character"]
    tools = avatar.tools
    stores = {"memory": avatar.memory.plugin, "persona": avatar.persona.plugin}
    if tools.mcp.enabled and tools.mcp.plugin is not None:
        stores["mcp"] = tools.mcp.plugin
    for capability, name in stores.items():
        needs[capability] = [f"alpha-avatar-plugins-{capability}"]
        if name == "default":  # The default plugins keep vectors in a local or remote store.
            needs[capability].append("alpha-avatar-agents[vdb]")
    for name in ("deepresearch", "rag"):
        if getattr(tools, name).plugin is not None:
            needs[name] = [f"alpha-avatar-plugins-{name}"]

    seen: set[tuple[str, str]] = set()
    _unmet(Requirement(HOST), seen)  # Reported by packages.alphaavatar, not again here.
    missing: set[str] = set()
    for capability, requirements in needs.items():
        for requirement in requirements:
            found = _unmet(Requirement(requirement), seen)
            problems += [f"{capability}: {problem}" for problem in found]
            if found:
                missing.add(requirement)
    enabled = ", ".join(needs)
    problems = list(dict.fromkeys(problems))  # One package can reach a capability twice.
    unknown = tuple(f"provider backends not verified: {item}" for item in unverified)
    if problems:
        return Check(
            "packages.capabilities",
            "FAIL",
            "Enabled capabilities miss packages",
            (*problems, *unknown),
            "Install into this Python environment: "
            + (" ".join(f"'{item}'" for item in sorted(missing)) or "the named plugins"),
        )
    if unknown:
        return Check(
            "packages.capabilities",
            "WARN",
            f"Requirements installed for {enabled}; some provider backends not verified",
            unknown,
            f"`{_dev(source)}` builds these plugins and reports a missing package or field",
        )
    return Check("packages.capabilities", "PASS", f"Requirements installed for {enabled}")


def _runners(config: ApplicationConfig) -> Check:
    from alphaavatar.agents.runtime.inference import plan_inference_runners

    runners = plan_inference_runners(config.avatar)
    inference = config.avatar.runtime.inference
    # As config check summarizes them: only the methods with several workers are named.
    parallel = [
        f"{method} x{count}" for method in runners if (count := inference.workers(method)) > 1
    ]
    workers = f"workers: {', '.join(parallel)}" if parallel else "1 worker each"
    return Check("config.runners", "PASS", f"{len(runners)} runners ({workers}); plan is valid")


def _dev(source: ConfigSource) -> str:
    if source.default:
        return "alphaavatar dev"
    return f"alphaavatar dev {source.bundle if source.bundle is not None else source.path}"


def _models(config: ApplicationConfig, source: ConfigSource) -> Check:
    from alphaavatar.agents.runtime.inference import plan_inference_runners

    count = len(plan_inference_runners(config.avatar))
    if not count:
        return Check("models.runners", "SKIP", "No runner selected, so no model to verify")
    return Check(
        "models.runners",
        "SKIP",
        f"Not verified: static checks load and download no model for the {count} runners",
        action=f"`{_dev(source)}` initializes every runner, fetching missing models, "
        "before it accepts a session",
    )


def _services(config: ApplicationConfig, source: ConfigSource) -> Check:
    from alphaavatar.agents.utils.vdb.config import vdb_backend

    avatar = config.avatar
    services = [f"{config.host.rtc.backend} RTC server"]
    if backends := sorted(_provider_backends(config)[0]):
        services.append(f"model providers ({', '.join(backends)})")
    if speech := [part.plugin for part in (avatar.voice.stt, avatar.voice.tts) if part.plugin]:
        services.append(f"speech services ({', '.join(speech)})")
    mcp = avatar.tools.mcp
    stores = [avatar.memory, avatar.persona] + ([mcp] if mcp.enabled and mcp.plugin else [])
    if any(s.plugin == "default" and vdb_backend(s.vdb_config) == "qdrant" for s in stores):
        services.append("Qdrant")
    if tools := [name for name in ("deepresearch", "rag") if getattr(avatar.tools, name).plugin]:
        services.append(f"tool services ({', '.join(tools)})")
    if mcp.enabled and mcp.plugin is not None:
        services.append(f"{len(mcp.servers)} MCP server{'' if len(mcp.servers) == 1 else 's'}")
    return Check(
        "services.external",
        "SKIP",
        "Not verified: static checks contact no service",
        tuple(services),
        f"`{_dev(source)}` connects to them; credentials and access are checked there",
    )


def _home(paths: ApplicationPaths, overrides: Sequence[str]) -> Check:
    from alphaavatar.host.configs import application_paths, format_failure, read_settings

    if paths.root != application_paths(overrides).root:
        chosen = "the configuration file"
    elif any(item.partition("=")[0].strip() == "application.home" for item in overrides):
        chosen = "the application.home override"
    elif os.environ.get("ALPHAAVATAR_HOME"):
        chosen = "ALPHAAVATAR_HOME"
    else:
        chosen = "the platform default"
    unreadable = None
    try:
        default = read_settings(paths).get("default_bundle")
        settings = f"default bundle {default}" if default is not None else "no default bundle"
    except Exception as error:
        settings, unreadable = "unreadable", error
    bundles = paths.configs.bundles_dir
    count = len(list(bundles.glob("*.yaml"))) if bundles.is_dir() else 0
    notes = (f"chosen by {chosen}", f"settings: {settings}", f"{count} bundle{'s' * (count != 1)}")
    check = _directory("paths.home", paths.root, notes)
    if unreadable is None or check.status == "FAIL":
        return check
    # Named bundles and files still load; the default bundle and config init need settings.
    action = f"Fix or remove {paths.settings_file}; config init and runs without a bundle read it"
    return Check(
        "paths.home",
        "WARN",
        f"{check.summary}: settings unreadable",
        (*check.details, *(line.strip() for line in format_failure(unreadable).splitlines())),
        f"{action}; {check.action}" if check.action else action,
    )


def _cache(paths: ApplicationPaths) -> Check:
    models = paths.cache.models_dir
    state = "present" if models.is_dir() and any(models.iterdir()) else "none yet"
    return _directory("paths.cache", paths.cache.root, (f"downloaded models: {state}",))


def _directory(check_id: str, path: Path, notes: Sequence[str] = ()) -> Check:
    lines = list(notes)
    # The nearest existing ancestor; a link without a target stops creation, as a file does.
    nearest = path
    while not nearest.exists():
        if nearest.is_symlink():
            return Check(
                check_id,
                "FAIL",
                f"{nearest} is a symbolic link that does not resolve",
                ("; ".join(lines),) if lines else (),
                "Remove the link or create its target, or choose another location",
            )
        if nearest.parent == nearest:
            break
        nearest = nearest.parent
    if not nearest.is_dir():
        blocked = "" if nearest == path else f", so {path} cannot be created"
        return Check(
            check_id,
            "FAIL",
            f"{nearest} is not a directory{blocked}",
            ("; ".join(lines),) if lines else (),
            "Move it away or choose another location",
        )
    if nearest == path:
        info = path.stat()
        mine = info.st_uid == getattr(os, "geteuid", lambda: -1)()
        owner = "this user" if mine else "another user"
        state = f"{path}  ({stat.filemode(info.st_mode)}, owned by {owner})"
        usable = os.access(path, os.R_OK | os.W_OK | os.X_OK)
    else:
        state = f"{path}  (not created yet; created when first needed)"
        usable = os.access(nearest, os.W_OK | os.X_OK)
    free = shutil.disk_usage(nearest).free
    lines.append(f"{free / (1 << 30):.1f} GiB free")
    details = ("; ".join(lines),)
    if not usable:
        return Check(
            check_id,
            "FAIL",
            f"{state}: this user cannot write there",
            details,
            f"Give this user write access to {nearest}, or choose another location",
        )
    if free < MIN_FREE_BYTES:
        return Check(
            check_id,
            "WARN",
            f"{state}: less than 1 GiB free",
            details,
            "Free disk space, or choose a location on a larger disk",
        )
    return Check(check_id, "PASS", state, details)
