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

from typing import TYPE_CHECKING

from alphaavatar.agents.runtime.inference import InferenceRunner

from .config import RouterConfig

if TYPE_CHECKING:
    from alphaavatar.agents.configs.avatar_config import AvatarConfig


def configure_inference_runners(config: AvatarConfig) -> tuple[type[InferenceRunner], ...]:
    router = config.router
    if router.plugin != "default":
        return ()
    options = RouterConfig.model_validate(router.init_config)

    runners: list[type[InferenceRunner]] = []
    if options.addressing.semantic.enabled and config.voice.stt.plugin is not None:
        if options.addressing.semantic.model.name != "qwen3_0_6b_q8_0":
            raise ValueError(
                f"Unknown semantic addressing model: {options.addressing.semantic.model.name}"
            )
        from .processors.addressing.semantic.runner import SemanticAddressingQwen3Runner

        runners.append(SemanticAddressingQwen3Runner)

    if options.turn_taking.enabled:
        if options.turn_taking.model.name != "smart_turn_v3":
            raise ValueError(f"Unknown turn-taking model: {options.turn_taking.model.name}")
        from .processors.turn_taking.runner.smart_turn_v3 import SmartTurnV3Runner

        runners.append(SmartTurnV3Runner)
    return tuple(runners)
