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

from typing import Any

from alphaavatar.agents.persona import PersonaBase, PersonaProcessorBase
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.runtime.plugin import AvatarModulePlugin

from .config import DefaultPersonaConfig
from .log import logger
from .processors import FaceProcessor, ProfilerProcessor, SpeakerProcessor
from .runtime import PersonaRuntime
from .storage import PersonaStore
from .version import __version__


class PersonaPlugin(AvatarModulePlugin):
    def __init__(self) -> None:
        super().__init__(__name__, __version__, __package__, logger)

    def get_plugin(
        self,
        *,
        runtime: AvatarRuntime,
        init_config: dict[str, Any] | None = None,
    ) -> PersonaBase:
        config = DefaultPersonaConfig.model_validate(init_config or {})
        store = PersonaStore(runtime=runtime)
        persona = PersonaRuntime(runtime=runtime, store=store)
        processors: list[PersonaProcessorBase] = []

        if config.profiler.enabled:
            processors.append(
                ProfilerProcessor(runtime=runtime, persona=persona, config=config.profiler)
            )

        if config.speaker.enabled:
            processors.append(
                SpeakerProcessor(runtime=runtime, persona=persona, config=config.speaker)
            )

        if config.face.enabled:
            processors.append(FaceProcessor(runtime=runtime, persona=persona, config=config.face))

        persona.bind_processors(processors)
        return persona
