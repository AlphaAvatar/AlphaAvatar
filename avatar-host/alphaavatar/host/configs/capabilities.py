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
"""What a configuration's selections need installed, by the setting that selects each.

Start builds the RTC backend, the loop and context their entry points name, a module factory
for every plugin selection, the provider backends of the tasks it creates, and the planned
inference runners. Each comes from an installed package, often with an extra: the same
requirements `alphaavatar setup` installs. Resolving imports the selected plugins, which only
registers them, and reads package metadata; no runner, model, client or session starts.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from typing import TYPE_CHECKING, Any

from .bundles import ConfigReferenceError

if TYPE_CHECKING:
    from packaging.requirements import Requirement

    from .application import ApplicationConfig

HOST = "alpha-avatar-host"


@dataclass(frozen=True, slots=True)
class Need:
    location: str  # The setting that selects it, e.g. voice.vad.plugin.
    requirement: str  # A PEP 508 requirement, e.g. alpha-avatar-plugins-voice[silero].


@dataclass(frozen=True, slots=True)
class Capabilities:
    needs: tuple[Need, ...]
    problems: tuple[str, ...]  # Selections no installed package serves, by location.
    unverified: tuple[str, ...]  # Another plugin's settings: its provider backends are unknown.

    def missing(self) -> dict[Need, list[str]]:
        """Each need's missing or mismatched packages; Host requirements count as reported."""
        from packaging.requirements import Requirement

        seen: set[tuple[str, str]] = set()
        unmet(Requirement(HOST), seen)
        found = {need: unmet(Requirement(need.requirement), seen) for need in self.needs}
        return {need: problems for need, problems in found.items() if problems}


def unmet(requirement: Requirement, seen: set[tuple[str, str]]) -> list[str]:
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
    provided = {
        canonicalize_name(extra) for extra in distribution.metadata.get_all("Provides-Extra") or ()
    }
    problems += [
        f"{requirement.name} {distribution.version} has no extra {extra!r}"
        for extra in sorted(requirement.extras)
        if canonicalize_name(extra) not in provided
    ]
    for text in distribution.requires or ():
        child = Requirement(text)
        if child.marker is None:
            wanted = "" in extras
        else:
            wanted = any(child.marker.evaluate({"extra": extra}) for extra in extras)
        if wanted:
            problems += unmet(child, seen)
    return problems


def with_extra(distribution: str, name: str) -> str:
    """A distribution with the extra named after the selected backend, if it has one."""
    try:
        extras = metadata.metadata(distribution).get_all("Provides-Extra") or []
    except metadata.PackageNotFoundError:
        return distribution  # Reported as not installed when checked.
    return f"{distribution}[{name}]" if name in extras else distribution


def provider_backends(config: ApplicationConfig) -> tuple[dict[str, str], list[str]]:
    """Backends of the provider tasks start would create, each with its first setting.

    Built-in plugins' settings are validated as at start, so omitted fields take their
    defaults. A processor switched off creates nothing, so its tasks are skipped; a disabled
    plugin is not read. Vector store embeddings always use the default backend. Another
    plugin's backends cannot be read statically and are returned as unverified.
    """
    from pydantic import BaseModel

    from alphaavatar.agents.avatar.provider.schemas import ProviderTaskConfig

    from .loader import validate_plugin_settings

    avatar = config.avatar
    settings = validate_plugin_settings(config)
    default = ProviderTaskConfig.model_fields["backend"].default
    backends: dict[str, str] = {}
    unverified: list[str] = []

    def collect(value: Any, location: str) -> None:
        if isinstance(value, ProviderTaskConfig):
            backends.setdefault(value.backend, f"{location}.backend")
        elif isinstance(value, BaseModel):
            if getattr(value, "enabled", True) is False:
                return  # Switched off: start creates neither the processor nor its tasks.
            for name in type(value).model_fields:
                collect(getattr(value, name), f"{location}.{name}")
        elif isinstance(value, dict):
            for key, item in value.items():
                collect(item, f"{location}.{key}")
        elif isinstance(value, list | tuple):
            for index, item in enumerate(value):
                collect(item, f"{location}.{index}")

    if "loop" in settings:
        collect(settings["loop"], "loop.init_config")
    else:
        unverified.append(f"loop plugin {avatar.loop.plugin!r}")
    for name in ("memory", "persona"):
        if name in settings:
            collect(settings[name], f"{name}.init_config")
            # Its vector store embeds with the default backend.
            backends.setdefault(default, f"{name}.vdb_config.embedding")
        else:
            unverified.append(f"{name} plugin {getattr(avatar, name).plugin!r}")
    mcp = avatar.tools.mcp
    if mcp.enabled and mcp.plugin is not None:
        if mcp.plugin == "default":
            # Its tool index embeds with the default backend.
            backends.setdefault(default, "tools.mcp.vdb_config.embedding")
        else:
            unverified.append(f"mcp plugin {mcp.plugin!r}")
    return backends, unverified


def resolve_capabilities(config: ApplicationConfig) -> Capabilities:
    """Every requirement the selections need, and the selections nothing installed serves."""
    from alphaavatar.agents.runtime.inference import plan_inference_runners
    from alphaavatar.agents.runtime.plugin import AvatarModulePlugin, plugin_requirement

    avatar = config.avatar
    needs: list[Need] = [Need("host.rtc.backend", with_extra(HOST, config.host.rtc.backend))]
    problems: dict[str, str] = {}

    def entry_point(location: str, group: str, name: str) -> metadata.EntryPoint | None:
        # Loop, context and provider plugins are found by name, as start finds them.
        matches = tuple(metadata.entry_points(group=group, name=name))
        if len(matches) != 1 or matches[0].dist is None:
            problems[location] = f"{len(matches)} installed {group} plugins named {name!r}"
            return None
        needs.append(Need(location, with_extra(matches[0].dist.name, name)))
        return matches[0]

    for location, group in (
        ("loop.plugin", "alphaavatar.loop"),
        ("context.plugin", "alphaavatar.context"),
    ):
        found = entry_point(location, group, avatar.section(location).plugin)
        if found is not None:
            found.load()  # Registers its factory, as start does.
    backends, unverified = provider_backends(config)
    for backend, location in sorted(backends.items()):
        entry_point(location, "alphaavatar.provider", backend)
    packages = avatar.plugin_packages()
    needs += [Need(location, plugin_requirement(name)) for location, name in packages.items()]
    runners = plan_inference_runners(avatar)  # Imports the selected plugins: they register.
    for location, (module, name) in avatar.plugin_factories().items():
        if location not in problems and not AvatarModulePlugin.registered(module, name):
            problems[location] = f"no {module.value} factory {name!r} is registered"
    sections = {name: location for location, name in reversed(packages.items())}
    for method, runner in runners.items():
        # A runner belongs to the plugin whose package defines it.
        module = runner.__module__.split(".")
        plugin = module[2] if module[:2] == ["alphaavatar", "plugins"] else None
        location = f"{sections.get(plugin, 'runtime.inference')} (runner {method})"
        needs += [Need(location, requirement) for requirement in runner.REQUIRES]
    return Capabilities(
        tuple(dict.fromkeys(needs)),
        tuple(f"{location}: {problem}" for location, problem in problems.items()),
        tuple(unverified),
    )


def check_capabilities(config: ApplicationConfig) -> Capabilities:
    """Each selection served by an installed package with its requirements; else one error."""
    capabilities = resolve_capabilities(config)
    lines = list(capabilities.problems)
    for need, problems in capabilities.missing().items():
        lines += [f"{need.location}: {need.requirement}: {problem}" for problem in problems]
    if lines:
        raise ConfigReferenceError(
            "Selected capabilities are not installed; `alphaavatar setup` installs them, or "
            "change the settings that select them:"
            + "".join(f"\n      {line}" for line in dict.fromkeys(lines))
        )
    return capabilities
