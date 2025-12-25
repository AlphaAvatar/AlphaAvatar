# Copyright 2025 AlphaAvatar project
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
import threading
from enum import Enum

from livekit.agents import Plugin

from .log import logger


class AvatarModule(str, Enum):
    """"""

    # Internal module names
    CHARACTER = "character"
    MEMORY = "memory"
    PROFILER = "persona_profiler"
    SPEAKER = "persona_speaker"
    RECOGNIZER = "persona_recognizer"

    # tools
    DEEPRESEARCH = "deepresearch"


class AvatarPlugin(Plugin):
    avatar_registered_plugins: dict[AvatarModule, dict[str, Plugin]] = {
        module_name: {} for module_name in AvatarModule
    }

    @classmethod
    def register_avatar_plugin(cls, module: AvatarModule, name: str, plugin: Plugin) -> None:
        if threading.current_thread() != threading.main_thread():
            raise RuntimeError("Plugins must be registered on the main thread")

        if name in cls.avatar_registered_plugins[module]:
            raise ValueError(f"AvatarPlugin[{module}] `{name}` already registered.")

        cls.avatar_registered_plugins[module][name] = plugin
        cls.register_plugin(plugin)

    @classmethod
    def get_avatar_plugin(cls, module: AvatarModule, name: str, *args, **kwargs):
        module_plugins = cls.avatar_registered_plugins[module]
        if name not in module_plugins:
            logger.warning(
                f"We only supoort the following [{module}] plugins right now, please check again:\n{list(module_plugins.keys())}"
            )
            return None

        return module_plugins[name].get_plugin(*args, **kwargs)  # type: ignore
