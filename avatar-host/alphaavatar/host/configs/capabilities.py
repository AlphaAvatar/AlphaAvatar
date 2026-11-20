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
its ``REQUIRES``. In an installed package, what `alphaavatar setup` offers is named as such,
with the command for the bundle the configuration came from.
Resolving loads factory modules and reads package metadata; no runner, model, client or
session starts.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from typing import TYPE_CHECKING

from alphaavatar.host.version import DISTRIBUTION as HOST

from .problems import ConfigProblems, Problem, setup_installs

if TYPE_CHECKING:
    from packaging.requirements import Requirement

    from alphaavatar.agents.runtime.plugin import PluginSelection, UnavailablePlugins

    from .application import ApplicationConfig
    from .bundles import ConfigSource


class MissingCapabilities(ConfigProblems):
    """Selections the installed packages do not serve; each problem says what would: the
    setting, what is wrong, the package that would serve it and what installs it, where known."""


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
    Its catalog's, which `setup <bundle>` plans a bundle's selections from: MCP's too, though no
    question of an asked setup selects it.
    """
    from alphaavatar.host.tools.setup.environment import Installation, SetupError

    try:
        return Installation.running().catalog.get("plugins", {})
    except SetupError:
        return None


def unavailable(
    error: UnavailablePlugins, source: ConfigSource | None = None
) -> MissingCapabilities:
    """Every unavailable selection, with what installs it where that is known: for the bundle
    ``source`` names, its setup command."""
    from packaging.requirements import Requirement

    setup = offered()
    items = []
    for location, problem in error.problems.items():
        module, name = error.selection.selected[location]
        line, package, action = f"{location}: {problem}", None, None
        if problem.missing and setup is not None:
            if package := setup.get(module.value, {}).get(name):
                action = setup_installs(source)
                line += f"; {action} ({package})"
            else:
                action = "this release's `alphaavatar setup` does not offer it"
                line += f"; {action}"
        elif problem.distribution is not None:
            found = unmet(Requirement(with_extra(problem.distribution, name)), set())
            line += "".join(f"; {item}" for item in found)
            package = with_extra(problem.distribution, name) if found else None
        items.append(Problem(line, location, str(problem), package, action))
    return MissingCapabilities(
        "Selected plugins are not available; install them, or change the settings that select them",
        tuple(items),
    )


def resolve_capabilities(config: ApplicationConfig) -> Capabilities:
    """Every requirement the selections need, resolved as start resolves them."""
    from alphaavatar.agents.runtime.plugin import resolve_plugins

    selection = resolve_plugins(config.avatar)
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
    """Each selection served by an installed package with its requirements; else one error,
    naming the setup command for the bundle the configuration came from."""
    from alphaavatar.agents.runtime.plugin import UnavailablePlugins

    capabilities = resolve_capabilities(config)
    if capabilities.selection.problems:
        raise unavailable(UnavailablePlugins(capabilities.selection), config.source)
    from alphaavatar.host.tools.setup.choices import requirements_offered

    installs = requirements_offered() if offered() is not None else frozenset()
    items: dict[str, Problem] = {}
    for need, problems in capabilities.missing().items():
        action = setup_installs(config.source) if need.requirement in installs else None
        suffix = f" ({action})" if action else ""
        for problem in problems:
            line = f"{need.location}: {need.requirement}: {problem}{suffix}"
            items.setdefault(line, Problem(line, need.location, problem, need.requirement, action))
    if items:
        raise MissingCapabilities(
            "Selected capabilities miss packages; install them, or change the settings that "
            "select them",
            tuple(items.values()),
        )
    return capabilities
