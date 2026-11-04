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
"""Doctor's checks and their order: static checks here, the diagnostic session in ``session``.

Selection, loading and the output boundary are the public services `config check`, `start`
and `dev` use. The static checks create, download, load, start and contact nothing. The
diagnostic session then runs the configured chain on fixed samples in a process of its own
(``process``), reaching external services only when ``host.doctor.external_services`` allows
it; a plugin Doctor does not ship counts as one, since what it reaches is unknown. What it
cannot run is reported as not verified, never as passing. The report is plain data for the
CLI, an App or a TUI.
"""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import socket
import stat
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .enums import CheckStatus
from .schemas import Check, CheckSpec, Evidence, Report

if TYPE_CHECKING:
    from packaging.requirements import Requirement

    from alphaavatar.core.workspace import ApplicationPaths
    from alphaavatar.host.configs import ApplicationConfig, ConfigSource

HOST = "alpha-avatar-host"
MIN_FREE_BYTES = 1 << 30  # Less leaves little room for models, caches and Avatar data.
# The plugins and provider backends this release ships, whose reach Doctor knows. Any other
# name is a custom plugin: what it reaches cannot be confirmed, so it needs authorization.
_BUILT_IN = {
    "loop": ("realtime",),
    "context": ("default",),
    "router": ("default",),
    "status": ("default",),
    "voice.vad": ("silero",),
    "voice.stt": ("openai_realtime", "openai_segment"),
    "voice.tts": ("openai", "voiceai"),
    "memory": ("default",),
    "persona": ("default",),
    "character": ("airi",),
    "tools.deepresearch": ("default",),
    "tools.rag": ("default",),
    "tools.mcp": ("default",),
    "provider backend": ("langchain", "openai"),
}


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
    CheckSpec(
        "session.start", "A temporary session of the configuration: start, ready", True, True
    ),
    CheckSpec(
        "models.runners", "Planned runners started from the model cache, offline", True, True
    ),
    CheckSpec("services.external", "Model, speech, vector store and tool services", True),
    CheckSpec("session.scenarios", "Fixed samples through each enabled modality chain", True, True),
    CheckSpec("session.cleanup", "Session, runners, sockets and files reclaimed", True, True),
    CheckSpec("devices.media", "Microphones, cameras and players: client devices, not opened"),
)


async def diagnose(
    target: str | None = None,
    overrides: Sequence[str] = (),
    *,
    read_env: Callable[[], object] | None = None,
    stop: asyncio.Event | None = None,
) -> Report:
    """Every check in ``CHECKS`` order; one that cannot complete is reported as FAIL.

    ``target`` and ``overrides`` mean what they mean for ``config check``. ``read_env``, if
    given, loads the environment file first, as ``start`` does; its failure is reported.
    Setting ``stop`` interrupts the diagnostic session: what runs is closed and reported, and
    the rest is reported as not run. Cancelling this call also closes what runs first.
    """
    diagnosis = await asyncio.to_thread(prepare, target, overrides, read_env=read_env)
    return await diagnosis.run(stop=stop) if diagnosis.starts else diagnosis.report()


def prepare(
    target: str | None = None,
    overrides: Sequence[str] = (),
    *,
    read_env: Callable[[], object] | None = None,
) -> Diagnosis:
    """The static checks, without an event loop: opening nothing, not even a local socket."""
    checks, loaded = _static(target, overrides, read_env)
    return Diagnosis(checks, loaded, tuple(overrides))


@dataclass(frozen=True, slots=True)
class Diagnosis:
    """The static checks, then the diagnostic session if it has anything to start."""

    checks: dict[str, Check]
    loaded: tuple[ApplicationConfig, ConfigSource] | None
    overrides: tuple[str, ...]

    @property
    def _planned(self) -> bool:
        return self.loaded is not None and self.checks["config.runners"].status == "PASS"

    @property
    def starts(self) -> bool:
        """Whether ``run`` starts a session or runners; ``report`` suffices otherwise."""
        from .session import starts

        return self._planned and _safe_starts(
            lambda: starts(self.loaded[0], [name for name, _ in _external(self.loaded[0])])
        )

    def report(self) -> Report:
        """The report without running anything: the session's checks say why not."""
        checks = dict(self.checks)
        if self._planned:
            try:
                checks |= self._unstarted()
            except Exception as error:
                for check_id in (spec.id for spec in CHECKS if spec.in_session):
                    checks[check_id] = _incomplete(check_id, error)
        return self._finish(checks)

    async def run(self, *, stop: asyncio.Event | None = None) -> Report:
        """The static checks with the diagnostic session's, from one configuration snapshot:
        what was authorized is what the diagnostic process starts."""
        from . import process

        config, source = self.loaded
        checks = dict(self.checks)
        try:
            checks |= await process.diagnose(
                config, source, _external(config), stop=stop or asyncio.Event()
            )
        except Exception as error:
            # Whatever ran is closed already; the report still names what could not complete.
            for check_id in (spec.id for spec in CHECKS if spec.in_session):
                checks[check_id] = _incomplete(check_id, error)
        return self._finish(checks)

    def _unstarted(self) -> dict[str, Check]:
        from .session import unstarted

        config, source = self.loaded
        return unstarted(config, source, _external(config))

    def _finish(self, checks: dict[str, Check]) -> Report:
        if self._planned and "services.external" not in checks:
            checks["services.external"] = _safely(
                "services.external", lambda: self._unstarted()["services.external"]
            )
        if self.loaded is None:
            reason, see = "Configuration not loaded", "config.load"
            if checks["config.load"].status == CheckStatus.WARN:
                reason = "No configuration selected"
        else:
            reason, see = "Runner plan not valid", "config.runners"
        for spec in CHECKS:
            checks.setdefault(spec.id, Check(spec.id, CheckStatus.SKIP, f"{reason}; see {see}"))
        return _report(checks, self.loaded)


def _safe_starts(decide: Callable[[], bool]) -> bool:
    try:
        return decide()
    except Exception:
        return False  # report() then names the failure through the session's own checks.


def _static(
    target: str | None, overrides: Sequence[str], read_env: Callable[[], object] | None
) -> tuple[dict[str, Check], tuple[ApplicationConfig, ConfigSource] | None]:
    from alphaavatar.host.configs import application_paths

    loaded, load = _configuration(target, overrides, read_env)
    config = loaded[0] if loaded is not None else None
    checks = {
        "system.platform": _safely("system.platform", _platform),
        "python.version": _safely("python.version", _python),
        "packages.alphaavatar": _safely("packages.alphaavatar", _packages),
        "config.load": load,
        "devices.media": Check(
            "devices.media",
            CheckStatus.SKIP,
            "Not verified: the diagnostic session uses its own samples and opens no microphone, "
            "camera or player",
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
        }
    return checks, loaded


def _report(
    checks: dict[str, Check], loaded: tuple[ApplicationConfig, ConfigSource] | None
) -> Report:
    """The checks present, in ``CHECKS`` order, through the configuration output boundary."""
    from alphaavatar.host.configs import output_scrubber

    scrub = output_scrubber(loaded[0] if loaded is not None else None)

    def safe(text: str | None) -> str | None:
        return scrub(text) if text is not None else None

    def evidence(item: Evidence) -> Evidence:
        detail = {k: scrub(v) if isinstance(v, str) else v for k, v in item.detail.items()}
        return replace(item, detail=detail)

    return Report(
        tuple(
            replace(
                check,
                summary=scrub(check.summary),
                details=tuple(map(scrub, check.details)),
                action=safe(check.action),
                runners=tuple(
                    replace(
                        runner,
                        summary=scrub(runner.summary),
                        details=tuple(map(scrub, runner.details)),
                    )
                    for runner in check.runners
                ),
                scenarios=tuple(
                    replace(
                        result,
                        summary=scrub(result.summary),
                        details=tuple(map(scrub, result.details)),
                        blocked_stage=safe(result.blocked_stage),
                        cause=safe(result.cause),
                        transcript=safe(result.transcript),
                        answer=safe(result.answer),
                        evidence=tuple(map(evidence, result.evidence)),
                    )
                    for result in check.scenarios
                ),
                services=tuple(
                    replace(service, name=scrub(service.name), note=safe(service.note))
                    for service in check.services
                ),
            )
            for check in (checks[spec.id] for spec in CHECKS if spec.id in checks)
        )
    )


def _safely(check_id: str, run: Callable[[], Check]) -> Check:
    try:
        return run()
    except Exception as error:
        return _incomplete(check_id, error)


def _incomplete(check_id: str, error: Exception) -> Check:
    from alphaavatar.host.configs import format_failure

    return Check(
        check_id,
        CheckStatus.FAIL,
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
        format_failure,
        load_application,
        read_settings,
        select_configuration,
        validate_plugin_settings,
    )

    def failure(summary: str, error: Exception, action: str) -> Check:
        lines = (line.strip() for line in format_failure(error).splitlines())
        return Check(
            "config.load", CheckStatus.FAIL, summary, tuple(line for line in lines if line), action
        )

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
                    CheckStatus.WARN,
                    f"No configuration given and no default bundle in {paths.settings_file}",
                    action="Create one with `alphaavatar config init <name> --avatar-id <id>`, "
                    "or pass a bundle name or a configuration file",
                )
        source = select_configuration(target, overrides)
        config = load_application(source, overrides)
        check_application_paths(config)
        validate_plugin_settings(config)  # The steps config check and start take, in order.
    except Exception as error:
        if isinstance(error, ModuleNotFoundError) and error.name:
            action = f"Install the package that provides the Python module {error.name!r}"
        else:
            action = "Fix the reported field or reference, then run doctor again"
        return None, failure("The configuration did not load", error, action)
    return (config, source), Check(
        "config.load",
        CheckStatus.PASS,
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
            CheckStatus.FAIL,
            f"{system or sys.platform}: the Host needs the POSIX local socket API (AF_UNIX)",
            action="Run AlphaAvatar on Linux or macOS",
        )
    # Only the API is checked: opening a socket is left to start, as sandboxes may refuse it.
    return Check(
        "system.platform", CheckStatus.PASS, f"{system}; AF_UNIX socket API present, not opened"
    )


def _python() -> Check:
    from packaging.specifiers import SpecifierSet

    version, supported = platform.python_version(), metadata.metadata(HOST)["Requires-Python"]
    found = f"Python {version} ({platform.python_implementation()}) at {sys.executable}"
    if supported and not SpecifierSet(supported).contains(version, prereleases=True):
        return Check(
            "python.version",
            CheckStatus.FAIL,
            f"{found}; AlphaAvatar supports {supported}",
            action=f"Install AlphaAvatar into a Python {supported} environment",
        )
    return Check("python.version", CheckStatus.PASS, f"{found}; supported ({supported or 'any'})")


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
            CheckStatus.FAIL,
            "The Host's requirements are not all installed",
            tuple(problems),
            f"Install into this Python environment: '{HOST}'",
        )
    if len(releases) > 1:
        return Check(
            "packages.alphaavatar",
            CheckStatus.WARN,
            f"{count} AlphaAvatar packages from {len(releases)} releases",
            tuple(f"{version}: {', '.join(sorted(names))}" for version, names in releases.items()),
            "Install every AlphaAvatar package from the same release",
        )
    (release,) = releases
    return Check(
        "packages.alphaavatar",
        CheckStatus.PASS,
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
    """Backends of the provider tasks start would create, with their configuration defaults.

    Built-in plugins' settings are validated as at start, so omitted fields take their
    defaults. A processor switched off creates nothing, so its tasks are skipped; a disabled
    plugin is not read. Vector store embeddings always use the default backend. Another
    plugin's backends cannot be read statically and are returned as unverified.
    """
    from pydantic import BaseModel

    from alphaavatar.agents.avatar.provider.schemas import ProviderTaskConfig
    from alphaavatar.host.configs import validate_plugin_settings

    avatar = config.avatar
    settings = validate_plugin_settings(config)
    default = ProviderTaskConfig.model_fields["backend"].default
    backends: set[str] = set()
    unverified: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, ProviderTaskConfig):
            backends.add(value.backend)
        elif isinstance(value, BaseModel):
            if getattr(value, "enabled", True) is False:
                return  # Switched off: start creates neither the processor nor its tasks.
            for name in type(value).model_fields:
                collect(getattr(value, name))
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)
        elif isinstance(value, list | tuple):
            for item in value:
                collect(item)

    if "loop" in settings:
        collect(settings["loop"])
    else:
        unverified.append(f"loop plugin {avatar.loop.plugin!r}")
    for name in ("memory", "persona"):
        if name in settings:
            collect(settings[name])
            backends.add(default)  # Its vector store embeds with the default backend.
        else:
            unverified.append(f"{name} plugin {getattr(avatar, name).plugin!r}")
    mcp = avatar.tools.mcp
    if mcp.enabled and mcp.plugin is not None:
        if mcp.plugin == "default":
            backends.add(default)  # Its tool index embeds with the default backend.
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
            CheckStatus.FAIL,
            "Enabled capabilities miss packages",
            (*problems, *unknown),
            "Install into this Python environment: "
            + (" ".join(f"'{item}'" for item in sorted(missing)) or "the named plugins"),
        )
    if unknown:
        return Check(
            "packages.capabilities",
            CheckStatus.WARN,
            f"Requirements installed for {enabled}; some provider backends not verified",
            unknown,
            f"`{_dev(source)}` builds these plugins and reports a missing package or field",
        )
    return Check("packages.capabilities", CheckStatus.PASS, f"Requirements installed for {enabled}")


def _runners(config: ApplicationConfig) -> Check:
    from alphaavatar.agents.runtime.inference import plan_inference_runners

    runners = plan_inference_runners(config.avatar)
    inference = config.avatar.runtime.inference
    # As config check summarizes them: only the methods with several workers are named.
    parallel = [
        f"{method} x{count}" for method in runners if (count := inference.workers(method)) > 1
    ]
    workers = f"workers: {', '.join(parallel)}" if parallel else "1 worker each"
    return Check(
        "config.runners", CheckStatus.PASS, f"{len(runners)} runners ({workers}); plan is valid"
    )


def _command(name: str, source: ConfigSource) -> str:
    if source.default:
        return f"alphaavatar {name}"
    return f"alphaavatar {name} {source.bundle if source.bundle is not None else source.path}"


def _dev(source: ConfigSource) -> str:
    return _command("dev", source)


def _external(config: ApplicationConfig) -> list[tuple[str, str]]:
    """The external services the configured session reaches, by kind; the RTC server is apart.

    Kinds tell the diagnostic session which stage shows a service answered: model, stt, tts,
    qdrant, tools, mcp, or custom for a plugin whose reach is unknown.
    """
    from alphaavatar.agents.utils.vdb.config import vdb_backend

    avatar = config.avatar
    services = []
    backends = sorted(_provider_backends(config)[0])
    if backends:
        services.append((f"model providers ({', '.join(backends)})", "model"))
    voice = avatar.voice
    if voice.stt.plugin:
        services.append((f"speech recognition ({voice.stt.plugin})", "stt"))
    if voice.tts.plugin:
        services.append((f"speech synthesis ({voice.tts.plugin})", "tts"))
    mcp = avatar.tools.mcp
    stores = [avatar.memory, avatar.persona] + ([mcp] if mcp.enabled and mcp.plugin else [])
    if any(s.plugin == "default" and vdb_backend(s.vdb_config) == "qdrant" for s in stores):
        services.append(("Qdrant", "qdrant"))
    if tools := [name for name in ("deepresearch", "rag") if getattr(avatar.tools, name).plugin]:
        services.append((f"tool services ({', '.join(tools)})", "tools"))
    if mcp.enabled and mcp.plugin is not None:
        count = len(mcp.servers)
        services.append((f"{count} MCP server{'' if count == 1 else 's'}", "mcp"))
    chosen = {
        "loop": avatar.loop.plugin,
        "context": avatar.context.plugin,
        "router": avatar.router.plugin,
        "status": avatar.status.plugin if avatar.status.enabled else None,
        "voice.vad": voice.vad.plugin,
        "voice.stt": voice.stt.plugin,
        "voice.tts": voice.tts.plugin,
        "memory": avatar.memory.plugin,
        "persona": avatar.persona.plugin,
        "character": avatar.character.plugin,
        "tools.deepresearch": avatar.tools.deepresearch.plugin,
        "tools.rag": avatar.tools.rag.plugin,
        "tools.mcp": mcp.plugin if mcp.enabled else None,
    }
    custom = [(part, name) for part, name in chosen.items() if name is not None]
    custom += [("provider backend", name) for name in backends]
    for part, name in custom:
        if name not in _BUILT_IN[part]:
            services.append((f"custom {part} {name!r}", "custom"))
    return services


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
    if unreadable is None or check.status == CheckStatus.FAIL:
        return check
    # Named bundles and files still load; the default bundle and config init need settings.
    action = f"Fix or remove {paths.settings_file}; config init and runs without a bundle read it"
    return Check(
        "paths.home",
        CheckStatus.WARN,
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
                CheckStatus.FAIL,
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
            CheckStatus.FAIL,
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
            CheckStatus.FAIL,
            f"{state}: this user cannot write there",
            details,
            f"Give this user write access to {nearest}, or choose another location",
        )
    if free < MIN_FREE_BYTES:
        return Check(
            check_id,
            CheckStatus.WARN,
            f"{state}: less than 1 GiB free",
            details,
            "Free disk space, or choose a location on a larger disk",
        )
    return Check(check_id, CheckStatus.PASS, state, details)
