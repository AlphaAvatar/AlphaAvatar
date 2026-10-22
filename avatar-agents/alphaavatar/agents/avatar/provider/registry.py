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

from .schemas import ProvidersConfig, ProviderTaskConfig


class ProviderRegistry:
    """A private task-config snapshot; returned values cannot mutate active bindings."""

    def __init__(self, config: ProvidersConfig | None = None) -> None:
        self._config = (config or ProvidersConfig()).model_copy(deep=True)

    @property
    def config(self) -> ProvidersConfig:
        return self._config.model_copy(deep=True)

    def get_task_config(self, task_name: str) -> ProviderTaskConfig:
        try:
            return self._config.tasks[task_name].model_copy(deep=True)
        except KeyError as exc:
            raise KeyError(f"Provider task {task_name!r} is not configured") from exc

    def has_task(self, task_name: str) -> bool:
        return task_name in self._config.tasks

    def validate_tasks(self, task_names: Iterable[str]) -> None:
        missing = [name for name in task_names if not self.has_task(name)]
        if missing:
            raise KeyError("Missing provider task config: " + ", ".join(missing))
