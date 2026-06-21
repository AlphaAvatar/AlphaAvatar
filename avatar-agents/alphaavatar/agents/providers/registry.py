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
from collections.abc import Iterable

from alphaavatar.agents.providers.schema import ProvidersConfig, ProviderTaskConfig


class ProviderRegistry:
    def __init__(self, config: ProvidersConfig | None = None) -> None:
        self._config = config or ProvidersConfig()

    @property
    def config(self) -> ProvidersConfig:
        return self._config

    def get_task_config(self, task_name: str) -> ProviderTaskConfig:
        task_config = self._config.tasks.get(task_name)

        if task_config is None:
            raise KeyError(
                f"Provider task '{task_name}' is not configured. "
                "Please add it to plugin provider.tasks config."
            )

        return task_config

    def has_task(self, task_name: str) -> bool:
        return task_name in self._config.tasks

    def validate_tasks(self, task_names: Iterable[str]) -> None:
        missing_tasks = [task_name for task_name in task_names if not self.has_task(task_name)]

        if missing_tasks:
            raise KeyError("Missing provider task config: " + ", ".join(missing_tasks))
