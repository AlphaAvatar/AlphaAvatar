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

from typing import TYPE_CHECKING, Any

from alphaavatar.agents.runtime.plugin import AvatarModulePlugin
from alphaavatar.core.output import OutputLane

from .config import RouterConfig
from .log import logger
from .processors import (
    AudioActivityProcessor,
    MultimodalTurnTakingProcessor,
    SemanticAddressingProcessor,
    SpeechSynthesisProcessor,
    SpeechTranscriptionProcessor,
    TranscriptSynchronizationProcessor,
    VisualAddressingProcessor,
)
from .runtime import InteractionRouterRuntime
from .version import __version__

if TYPE_CHECKING:
    from alphaavatar.agents.router import RouterProcessorBase
    from alphaavatar.agents.runtime import AvatarRuntime


class RouterPlugin(AvatarModulePlugin):
    def __init__(self) -> None:
        super().__init__(__name__, __version__, __package__, logger)

    def get_plugin(
        self,
        *,
        runtime: AvatarRuntime,
        init_config: dict[str, Any] | None = None,
    ) -> InteractionRouterRuntime:
        config = RouterConfig.model_validate(init_config or {})
        voice = runtime.foundation.voice
        processors: list[RouterProcessorBase] = []

        if voice.vad is not None and config.audio_activity.enabled:
            processors.append(
                AudioActivityProcessor(runtime=runtime, vad=voice.vad, config=config.audio_activity)
            )

        if voice.stt is not None:
            processors.append(SpeechTranscriptionProcessor(runtime=runtime, stt=voice.stt))

        if voice.tts is not None:
            processors.extend(
                (
                    TranscriptSynchronizationProcessor(
                        runtime=runtime, lanes=(OutputLane.TRANSIENT,)
                    ),
                    SpeechSynthesisProcessor(
                        runtime=runtime, tts=voice.tts, lanes=(OutputLane.TRANSIENT,)
                    ),
                )
            )

        if config.addressing.visual.enabled:
            processors.append(
                VisualAddressingProcessor(runtime=runtime, config=config.addressing.visual)
            )

        required_addressing_sources: tuple[str, ...] = ()
        if config.addressing.semantic.enabled and voice.stt is not None:
            processors.append(
                SemanticAddressingProcessor(runtime=runtime, config=config.addressing.semantic)
            )
            required_addressing_sources = (SemanticAddressingProcessor.SEMANTIC_SOURCE,)

        if config.turn_taking.enabled:
            processors.append(
                MultimodalTurnTakingProcessor(
                    runtime=runtime,
                    config=config.turn_taking,
                    required_addressing_sources=required_addressing_sources,
                )
            )

        return InteractionRouterRuntime(runtime=runtime, processors=processors)
