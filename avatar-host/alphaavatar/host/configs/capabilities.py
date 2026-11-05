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

The selections resolve as start resolves them (``resolve_plugins``): each implementation by
capability type and name from the installed package declaring it, the provider backends their
settings name, and the inference runners they use. Each needs its package, with the extra
named after it when the package has one; the RTC backend needs its Host extra and each runner
its ``REQUIRES``. In an installed package, what `alphaavatar setup` offers is named as such.
Resolving loads factory modules and reads package metadata; no runner, model, client or
session starts.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from typing import TYPE_CHECKING

from alphaavatar.host.version import DISTRIBUTION as HOST

from .bundles import ConfigReferenceError

if TYPE_CHECKING:
    from packaging.requirements import Requirement

    from alphaavatar.agents.runtime.plugin import PluginSelection, UnavailablePlugins

    from .application import ApplicationConfig


class MissingCapabilities(ConfigReferenceError):
    """Selections the installed packages do not serve; each line says what would."""


@dataclass(frozen=True, slots=True)
class Need:
    location: str  # The setting that selects it, e.g. voice.vad.plugin.
    requirement: str  # A PEP 508 requirement, e.g. alpha-avatar-plugins-voice[silero].


@dataclass(frozen=True, slots=True)
class Capabilities:
    needs: tuple[Need, ...]
    selection: PluginSelection

    @property
    def problems(self) -> tuple[str, ...]:
        """Selections no single installed implementation serves, by location."""
        return tuple(f"{location}: {error}" for location, error in self.selection.problems.items())

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


def offered() -> dict[str, dict[str, str]] | None:
    """By capability type and name, the requirement `alphaavatar setup` installs for each
    implementation it offers here; None outside an installed package, where it installs none.
    """
    from alphaavatar.host.setup.choices import requirements_offered
    from alphaavatar.host.setup.environment import Installation, SetupError

    try:
        catalog = Installation.running().catalog
    except SetupError:
        return None
    reachable = requirements_offered()
    return {
        module: {name: needed for name, needed in names.items() if needed in reachable}
        for module, names in catalog.get("plugins", {}).items()
    }


def unavailable(error: UnavailablePlugins) -> MissingCapabilities:
    """Every unavailable selection, with what installs it where that is known."""
    from packaging.requirements import Requirement

    setup = offered()
    lines = []
    for location, problem in error.problems.items():
        module, name = error.selection.selected[location]
        line = f"{location}: {problem}"
        if problem.missing and setup is not None:
            if needed := setup.get(module.value, {}).get(name):
                line += f"; `alphaavatar setup` installs it ({needed})"
            else:
                line += "; this release's `alphaavatar setup` does not offer it"
        elif problem.distribution is not None:
            found = unmet(Requirement(with_extra(problem.distribution, name)), set())
            line += "".join(f"; {item}" for item in found)
        lines.append(line)
    return MissingCapabilities(
        "Selected plugins are not available; install them, or change the settings that "
        "select them:" + "".join(f"\n      {line}" for line in lines)
    )


def resolve_capabilities(config: ApplicationConfig) -> Capabilities:
    """Every requirement the selections need, resolved as start resolves them."""
    from alphaavatar.agents.runtime.plugin import resolve_plugins

    selection = resolve_plugins(config.avatar, providers=True)
    needs = [Need("host.rtc.backend", with_extra(HOST, config.host.rtc.backend))]
    for location, plugin in selection.plugins.items():
        if plugin.distribution is not None:
            needs.append(Need(location, with_extra(plugin.distribution, plugin.name)))
    for location, error in selection.problems.items():
        if error.distribution is not None:  # Declared but not loading: its requirements tell.
            needs.append(
                Need(location, with_extra(error.distribution, selection.selected[location][1]))
            )
    for method, (location, runner) in selection.runners.items():
        needs += [Need(f"{location} (runner {method})", needed) for needed in runner.REQUIRES]
    return Capabilities(tuple(dict.fromkeys(needs)), selection)


def check_capabilities(config: ApplicationConfig) -> Capabilities:
    """Each selection served by an installed package with its requirements; else one error."""
    from alphaavatar.agents.runtime.plugin import UnavailablePlugins

    capabilities = resolve_capabilities(config)
    if capabilities.selection.problems:
        raise unavailable(UnavailablePlugins(capabilities.selection))
    from alphaavatar.host.setup.choices import requirements_offered

    installs = requirements_offered() if offered() is not None else frozenset()
    lines = []
    for need, problems in capabilities.missing().items():
        suffix = " (`alphaavatar setup` installs it)" if need.requirement in installs else ""
        lines += [f"{need.location}: {need.requirement}: {problem}{suffix}" for problem in problems]
    if lines:
        raise MissingCapabilities(
            "Selected capabilities miss packages; install them, or change the settings that "
            "select them:" + "".join(f"\n      {line}" for line in dict.fromkeys(lines))
        )
    return capabilities
