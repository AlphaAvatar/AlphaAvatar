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
from alphaavatar.agents import AvatarModule, AvatarPlugin
from alphaavatar.agents.interaction import InteractionRouterDependencies
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.runtime.inference import InferenceRunner
from alphaavatar.core.output import OutputLane

from .addressing.invocation import SherpaKeywordSpotterRunner, create_invocation_detector
from .config import DefaultRouterConfig
from .log import logger
from .processors import (
    AudioActivityProcessor,
    InvocationAddressingProcessor,
    MultimodalTurnTakingProcessor,
    SpeechSynthesisProcessor,
    SpeechTranscriptionProcessor,
    TranscriptSynchronizationProcessor,
    VisualAddressingProcessor,
)
from .processors.addressing.visual import FaceOrientationEstimator
from .processors.turn_taking import DefaultAddressingFusion, DefaultTurnTakingPolicy
from .runtime import InteractionRouterRuntime
from .turn_taking import SmartTurnV3Runner, create_turn_taking_model
from .version import __version__

__all__ = ["__version__"]


class DefaultRouterPlugin(AvatarPlugin):
    def __init__(self) -> None:
        super().__init__(__name__, __version__, __package__, logger)

    def _create_visual_addressing_processor(
        self,
        config: DefaultRouterConfig,
        runtime: AvatarRuntime,
    ) -> list:
        visual = config.addressing.visual

        if not visual.enabled:
            return []

        estimator = FaceOrientationEstimator(
            yaw_scale=visual.yaw_scale,
            roll_scale_deg=visual.roll_scale_deg,
            min_face_area_ratio=visual.min_face_area_ratio,
        )

        return [
            VisualAddressingProcessor(
                runtime=runtime,
                estimator=estimator,
                toward_threshold=visual.toward_threshold,
                away_threshold=visual.away_threshold,
                ema_alpha=visual.ema_alpha,
                min_samples=visual.min_samples,
                republish_interval_sec=(visual.republish_interval_sec),
                publish_away_evidence=(visual.publish_away_evidence),
            )
        ]

    def _create_invocation_addressing_processors(
        self,
        config: DefaultRouterConfig,
        runtime: AvatarRuntime,
    ) -> list:
        invocation = config.addressing.invocation

        if not invocation.enabled:
            return []

        detector = create_invocation_detector(
            invocation.provider,
            inference_executor=runtime.inference,
            phrases=tuple(phrase.build() for phrase in invocation.phrases),
            chunk_duration_ms=invocation.chunk_duration_ms,
            max_pending_chunks=invocation.max_pending_chunks,
            tail_padding_sec=invocation.tail_padding_sec,
        )

        return [
            InvocationAddressingProcessor(
                runtime=runtime,
                detector=detector,
                evidence_confidence=invocation.evidence_confidence,
                early_window_sec=invocation.early_window_sec,
                late_confidence_scale=invocation.late_confidence_scale,
            )
        ]

    def _create_turn_taking_processor(
        self,
        config: DefaultRouterConfig,
        runtime: AvatarRuntime,
    ) -> list:
        turn_taking = config.turn_taking
        fusion = config.addressing.fusion

        if not turn_taking.enabled:
            return []

        turn_model = create_turn_taking_model(
            turn_taking.model.name,
            inference_executor=runtime.inference,
        )
        turn_fusion = DefaultAddressingFusion(
            min_confidence=fusion.min_confidence,
            conflict_margin=fusion.conflict_margin,
        )
        turn_policy = DefaultTurnTakingPolicy(
            commit_threshold=turn_taking.policy.commit_threshold,
            audio_only_speech_start_interrupt=(
                turn_taking.interruption.enabled
                and turn_taking.interruption.audio_only_speech_start
            ),
            respond_to_group=turn_taking.policy.respond_to_group,
        )

        return [
            MultimodalTurnTakingProcessor(
                runtime=runtime,
                model=turn_model,
                policy=turn_policy,
                fusion=turn_fusion,
                addressing_wait_sec=config.addressing.addressing_wait_sec,
                transcript_wait_sec=turn_taking.transcript_wait_sec,
                max_hold_sec=turn_taking.policy.max_hold_sec,
                unsegmented_alignment_sec=turn_taking.unsegmented_alignment_sec,
            )
        ]

    def get_plugin(
        self,
        *,
        dependencies: InteractionRouterDependencies,
        init_config: dict | None = None,
    ):
        config = DefaultRouterConfig.model_validate(init_config or {})
        runtime = dependencies.runtime
        processors = []

        if dependencies.vad is not None and config.audio_activity.enabled:
            processors.append(
                AudioActivityProcessor(
                    runtime=runtime,
                    vad=dependencies.vad,
                    pre_roll_sec=config.audio_activity.pre_roll_sec,
                    max_buffer_sec=config.audio_activity.max_buffer_sec,
                )
            )

        processors.extend(self._create_visual_addressing_processor(config, runtime))
        processors.extend(self._create_invocation_addressing_processors(config, runtime))

        if dependencies.stt is not None:
            processors.append(
                SpeechTranscriptionProcessor(
                    runtime=runtime,
                    stt=dependencies.stt,
                )
            )

        processors.extend(self._create_turn_taking_processor(config, runtime))

        if dependencies.tts is not None:
            processors.extend(
                (
                    TranscriptSynchronizationProcessor(
                        runtime=runtime,
                        lanes=(OutputLane.TRANSIENT,),
                    ),
                    SpeechSynthesisProcessor(
                        runtime=runtime,
                        tts=dependencies.tts,
                        lanes=(OutputLane.TRANSIENT,),
                    ),
                )
            )

        return InteractionRouterRuntime(
            runtime=runtime,
            processors=processors,
        )


# Plugin register
AvatarPlugin.register_avatar_plugin(
    AvatarModule.INTERACTION_ROUTER,
    "default",
    DefaultRouterPlugin(),
)


# Inference Runners
InferenceRunner.register(SmartTurnV3Runner)
InferenceRunner.register(SherpaKeywordSpotterRunner)
