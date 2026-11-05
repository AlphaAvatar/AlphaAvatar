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

import importlib
import json
import os
from typing import TYPE_CHECKING

from pydantic import SecretStr
from pydantic_core import PydanticCustomError, ValidationError

from .runner import InferenceRunner

if TYPE_CHECKING:
    from alphaavatar.agents.configs.avatar_config import AvatarConfig
    from alphaavatar.agents.configs.runtime_config import InferenceConfig

INFERENCE_PLAN_ENV = "ALPHAAVATAR_INFERENCE_PLAN"


def _add_runner(runners: dict[str, type[InferenceRunner]], runner: type[InferenceRunner]) -> None:
    if not isinstance(runner, type) or not issubclass(runner, InferenceRunner):
        raise TypeError("Inference plans require InferenceRunner classes")
    method = getattr(runner, "INFERENCE_METHOD", None)
    if not isinstance(method, str) or not method or method != method.strip():
        raise ValueError("Inference runner method must be a nonempty trimmed string")
    if "<locals>" in runner.__qualname__ or runner.__module__ == "__main__":
        raise ValueError("Inference runners must be importable module-level classes")
    existing = runners.get(method)
    if existing is not None and existing is not runner:
        raise ValueError(f"Conflicting inference runners for {method!r}")
    runners[method] = runner


def snapshot_inference_config(config: AvatarConfig) -> str:
    """Private immutable launch inputs, under the namespace of each selected plugin whose
    runners read them (``InferenceRunner.config_for``); never expose these credentials in
    diagnostics.
    """
    from alphaavatar.agents.runtime.plugin import resolve_plugins

    def encode(value):
        if isinstance(value, SecretStr):
            return value.get_secret_value()
        raise TypeError("Inference configuration contains a non-JSON value")

    inputs = {}
    for location, plugin in resolve_plugins(config).plugins.items():
        section = config.section(location)
        if hasattr(section, "runner_config"):
            inputs[plugin.namespace] = section.runner_config()
    return json.dumps(
        inputs, default=encode, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )


def check_inference_config(
    runners: dict[str, type[InferenceRunner]], config: InferenceConfig
) -> None:
    """Overrides must name selected runners; only replicable runners take several workers.

    Failures are located at the offending override, since reports show locations only.
    """
    location = ("runtime", "inference", "methods")
    errors = [
        {
            "type": PydanticCustomError("unselected_runner", "Not a selected inference runner"),
            "loc": (*location, method),
            "input": options.workers,
        }
        for method, options in config.methods.items()
        if method not in runners
    ]
    errors += [
        {
            "type": PydanticCustomError("single_worker", "This inference runner is not REPLICABLE"),
            "loc": (*location, method, "workers"),
            "input": config.workers(method),
        }
        for method, runner in runners.items()
        if config.workers(method) > 1 and not runner.REPLICABLE
    ]
    if errors:
        raise ValidationError.from_exception_data("InferenceConfig", errors)


def plan_inference_runners(config: AvatarConfig) -> dict[str, type[InferenceRunner]]:
    """The runners the selected plugins use, checked against runtime.inference.

    Pure: it never writes the environment, spawns a process or loads a model. The selected
    plugins resolve first, and every one unavailable fails by the setting selecting it.
    """
    from alphaavatar.agents.runtime.plugin import resolve_plugins

    selection = resolve_plugins(config)
    selection.check()
    runners = {method: runner for method, (_, runner) in selection.runners.items()}
    check_inference_config(runners, config.runtime.inference)
    return runners


def prepare_inference_runners(config: AvatarConfig) -> tuple[str, ...]:
    """Build a configuration-specific, download-free plan before CLI subprocesses start."""
    os.environ.pop(INFERENCE_PLAN_ENV, None)
    runners = plan_inference_runners(config)
    plan = [
        {"method": method, "module": runner.__module__, "name": runner.__qualname__}
        for method, runner in runners.items()
    ]
    os.environ[INFERENCE_PLAN_ENV] = json.dumps(plan, separators=(",", ":"))
    return tuple(runners)


def bootstrap_inference_runners() -> dict[str, type[InferenceRunner]]:
    """Rebuild exactly the prepared plan in dev/start workers; never use the global catalog."""
    raw = os.getenv(INFERENCE_PLAN_ENV)
    if raw is None:
        raise RuntimeError(
            "Inference plan is missing; call prepare_inference_runners(config) first"
        )

    plan = json.loads(raw)
    if not isinstance(plan, list):
        raise ValueError("Inference plan must be a list")

    runners: dict[str, type[InferenceRunner]] = {}
    for item in plan:
        if not isinstance(item, dict) or set(item) != {"method", "module", "name"}:
            raise ValueError("Invalid inference plan entry")
        if any(not isinstance(value, str) or not value for value in item.values()):
            raise ValueError("Inference plan entries require nonempty strings")
        runner = importlib.import_module(item["module"])
        for part in item["name"].split("."):
            runner = getattr(runner, part)
        _add_runner(runners, runner)
        if runner.INFERENCE_METHOD != item["method"]:
            raise ValueError(f"Inference method changed for {item['module']}.{item['name']}")
    return runners
