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

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic import BaseModel

    from alphaavatar.agents.runtime.inference import InferenceRunner

    from ..module import AvatarModule
    from ..resolution import PluginError
    from .resolved_plugin import ResolvedPlugin


@dataclass(frozen=True, slots=True)
class PluginSelection:
    """A configuration's implementations, each by the setting that selects it."""

    selected: dict[str, tuple[AvatarModule, str]]
    plugins: dict[str, ResolvedPlugin] = field(default_factory=dict)
    problems: dict[str, PluginError] = field(default_factory=dict)
    # Resolved plugins' validated settings by section (``loop``), resolved with providers.
    settings: dict[str, BaseModel] = field(default_factory=dict)
    # By method: the setting whose plugin uses the runner, and the runner.
    runners: dict[str, tuple[str, type[InferenceRunner]]] = field(default_factory=dict)

    def check(self) -> None:
        from ..resolution import UnavailablePlugins  # resolution imports these schemas.

        if self.problems:
            raise UnavailablePlugins(self)
