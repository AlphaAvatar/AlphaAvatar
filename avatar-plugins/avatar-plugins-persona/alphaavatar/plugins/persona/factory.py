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

from alphaavatar.agents import AvatarModule, AvatarPlugin
from alphaavatar.agents.persona import PersonaBase, PersonaProcessorBase
from alphaavatar.agents.runtime import AvatarRuntime

from .log import logger
from .runtime import PersonaRuntime
from .storage import PersonaStore
from .version import __version__


def _create_processor(
    module: AvatarModule,
    config: dict[str, Any],
    *,
    runtime: AvatarRuntime,
    persona: PersonaBase,
) -> PersonaProcessorBase | None:
    if not config.get("enabled", True):
        return None

    processor = AvatarPlugin.get_avatar_plugin(
        module,
        config["plugin"],
        runtime=runtime,
        persona=persona,
        init_config=config["init_config"],
    )

    if not isinstance(processor, PersonaProcessorBase):
        raise TypeError(
            f"Persona plugin {module.value}:{config['plugin']} must return "
            f"PersonaProcessorBase, got {type(processor).__name__}."
        )

    return processor


class PersonaPlugin(AvatarPlugin):
    def __init__(self) -> None:
        super().__init__(__name__, __version__, __package__, logger)  # type: ignore

    def get_plugin(
        self,
        *,
        runtime: AvatarRuntime,
        init_config: dict[str, Any],
    ) -> PersonaBase:
        config = dict(init_config)

        profiler_config = config.pop("profiler")
        speaker_config = config.pop("speaker")
        face_config = config.pop("face")

        persona = PersonaRuntime(
            runtime=runtime,
            store=PersonaStore(runtime=runtime),
            **config,
        )

        processors = [
            processor
            for processor in (
                _create_processor(
                    AvatarModule.PROFILER,
                    profiler_config,
                    runtime=runtime,
                    persona=persona,
                ),
                _create_processor(
                    AvatarModule.SPEAKER,
                    speaker_config,
                    runtime=runtime,
                    persona=persona,
                ),
                _create_processor(
                    AvatarModule.FACE,
                    face_config,
                    runtime=runtime,
                    persona=persona,
                ),
            )
            if processor is not None
        ]

        persona.bind_processors(processors)
        return persona
