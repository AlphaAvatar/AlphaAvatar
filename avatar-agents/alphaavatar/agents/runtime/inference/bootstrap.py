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
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from alphaavatar.agents.log import logger

from .runner import InferenceRunner

INFERENCE_PLAN_ENV = "ALPHAAVATAR_INFERENCE_PLAN"
RunnerBootstrapFn = Callable[[Mapping[str, Any]], Iterable[type[InferenceRunner]]]
_runner_bootstraps: dict[str, RunnerBootstrapFn] = {}


def register_inference_runner_bootstrap(
    name: str, fn: RunnerBootstrapFn, *, override: bool = False
) -> None:
    if name in _runner_bootstraps and not override:
        logger.warning("Inference runner bootstrap already registered: %s, skipped", name)
        return
    _runner_bootstraps[name] = fn


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


def prepare_inference_runners(config: Mapping[str, Any]) -> tuple[str, ...]:
    """Build a configuration-specific, download-free plan before CLI subprocesses start."""
    os.environ.pop(INFERENCE_PLAN_ENV, None)
    runners: dict[str, type[InferenceRunner]] = {}
    for name, bootstrap in tuple(_runner_bootstraps.items()):
        try:
            for runner in bootstrap(config):
                _add_runner(runners, runner)
        except Exception as exc:
            raise RuntimeError(f"Failed to prepare inference runners for {name!r}") from exc

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
