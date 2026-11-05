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
from __future__ import annotations

from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Any

from .module import AvatarModule, AvatarModulePlugin
from .schemas import PluginSelection, ResolvedPlugin

if TYPE_CHECKING:
    from alphaavatar.agents.configs.avatar_config import AvatarConfig
    from alphaavatar.agents.runtime.inference import InferenceRunner


class PluginError(LookupError):
    """A selection no single installed implementation serves; the message is safe to show."""

    def __init__(
        self, message: str, distribution: str | None = None, *, missing: bool = False
    ) -> None:
        super().__init__(message)
        self.distribution = distribution  # The package declaring it, when one does.
        self.missing = missing  # No installed package declares it.


class UnavailablePlugins(PluginError):
    """Every selection not served, by the setting that makes it."""

    def __init__(self, selection: PluginSelection) -> None:
        self.selection, self.problems = selection, selection.problems
        lines = "".join(f"\n      {location}: {error}" for location, error in self.problems.items())
        super().__init__(f"Selected plugins are not available:{lines}")


_resolved: dict[tuple[AvatarModule, str], ResolvedPlugin] = {}


def resolve_plugin(module: AvatarModule, name: str) -> ResolvedPlugin:
    """The one installed implementation of ``module`` named ``name``, loaded once a process."""
    key = (AvatarModule(module), name)
    if key in _resolved:
        return _resolved[key]

    module = key[0]
    found = tuple(entry_points(group=module.group, name=name))
    if not found:
        raise PluginError(f"no installed package provides {module.value} {name!r}", missing=True)

    if len(found) > 1:
        packages = sorted(entry.dist.name if entry.dist else entry.value for entry in found)
        raise PluginError(
            f"{len(found)} installed packages provide {module.value} {name!r}: "
            + ", ".join(packages)
        )

    (entry,) = found
    distribution = entry.dist.name if entry.dist else None
    try:
        factory = entry.load()
        if not isinstance(factory, type) or not issubclass(factory, AvatarModulePlugin):
            raise TypeError(f"{entry.value} is not an AvatarModulePlugin class")
        _resolved[key] = ResolvedPlugin(module, name, factory(), distribution)
    except Exception as error:
        raise PluginError(
            f"{module.value} {name!r} from {distribution} does not load: "
            f"{type(error).__name__}: {error}",
            distribution,
        ) from error

    return _resolved[key]


def _provider_tasks(
    config: AvatarConfig, selection: PluginSelection
) -> dict[tuple[AvatarModule, str], str]:
    """The provider backends the resolved plugins' settings select, each by its first setting."""
    from pydantic import BaseModel, ValidationError
    from pydantic_core import PydanticCustomError

    from alphaavatar.agents.avatar.provider.enums import ProviderKind
    from alphaavatar.agents.configs.plugins.foundation.provider_config import ProviderTaskConfig

    errors: list[Any] = []
    for location, plugin in selection.plugins.items():
        section = location.rpartition(".")[0]
        if (init_config := getattr(config.section(location), "init_config", None)) is None:
            continue
        try:
            settings = plugin.factory.settings(init_config)
        except ValidationError as error:
            errors += [
                {
                    # The rendered message as context: braces in it are not a template.
                    "type": PydanticCustomError(
                        item["type"], "{message}", {"message": item["msg"]}
                    ),
                    "loc": (*section.split("."), "init_config", *item["loc"]),
                    "input": item["input"],
                }
                for item in error.errors(include_url=False)
            ]
            continue
        if settings is not None:
            selection.settings[section] = settings
    if errors:
        raise ValidationError.from_exception_data("PluginSettings", errors)

    tasks: dict[tuple[AvatarModule, str], str] = {}

    def collect(value: Any, location: str) -> None:
        if isinstance(value, ProviderTaskConfig):
            module = (
                AvatarModule.PROVIDER_LLM
                if value.kind == ProviderKind.LLM
                else AvatarModule.PROVIDER_EMBEDDING
            )
            tasks.setdefault((module, value.backend), f"{location}.backend")
        elif isinstance(value, BaseModel):
            if getattr(value, "enabled", True) is False:
                return  # Switched off: nothing creates its tasks.
            for name in type(value).model_fields:
                collect(getattr(value, name), f"{location}.{name}")
        elif isinstance(value, dict):
            for key, item in value.items():
                collect(item, f"{location}.{key}")
        elif isinstance(value, list | tuple):
            for index, item in enumerate(value):
                collect(item, f"{location}.{index}")

    for section, settings in selection.settings.items():
        collect(settings, f"{section}.init_config")
    return tasks


def resolve_plugins(config: AvatarConfig, *, providers: bool = False) -> PluginSelection:
    """Resolve each selected plugin, then the inference runners those plugins use.

    With ``providers``, each resolved plugin's settings are validated with its own schema,
    failing located under its section (``loop.init_config.model``), and the provider
    implementations resolve too: each ProviderTaskConfig in the settings outside a part
    switched off, and each a planned runner names (``InferenceRunner.PROVIDERS``). Unserved
    selections are problems by location; runners that cannot be planned fail at once.
    """
    from alphaavatar.agents.runtime.inference.bootstrap import _add_runner

    selection = PluginSelection(config.plugin_factories())
    runners: dict[str, type[InferenceRunner]] = {}

    def resolve(location: str, module: AvatarModule, name: str) -> None:
        selection.selected[location] = (module, name)
        try:
            selection.plugins[location] = resolve_plugin(module, name)
        except PluginError as error:
            selection.problems[location] = error

    def plan(plugins: dict[str, ResolvedPlugin]) -> None:
        for location, plugin in plugins.items():
            try:
                for runner in plugin.factory.inference_runners(config):
                    _add_runner(runners, runner)
                    selection.runners.setdefault(runner.INFERENCE_METHOD, (location, runner))
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to prepare the inference runners of {location} "
                    f"({plugin.module.value} {plugin.name!r})"
                ) from exc

    for location, (module, name) in list(selection.selected.items()):
        resolve(location, module, name)

    plan(dict(selection.plugins))
    if providers:
        tasks = _provider_tasks(config, selection)
        for method, (location, runner) in list(selection.runners.items()):
            for module, name in runner.PROVIDERS:
                tasks.setdefault((AvatarModule(module), name), f"{location} (runner {method})")
        sections = set(selection.plugins)
        for (module, name), location in tasks.items():
            resolve(location, module, name)
        plan({loc: plugin for loc, plugin in selection.plugins.items() if loc not in sections})

    return selection
