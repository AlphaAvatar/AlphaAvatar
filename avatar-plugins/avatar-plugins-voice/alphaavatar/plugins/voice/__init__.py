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
from alphaavatar.agents.runtime.inference import InferenceRunner
from alphaavatar.agents.runtime.plugin import AvatarModule, AvatarModulePlugin

from .log import logger
from .stt import OpenAIRealtimeSTTPlugin, OpenAISegmentSTTPlugin
from .tts import VoiceAITTSPlugin
from .vad import SileroVADPlugin, SileroVADRunner
from .version import __version__

__all__ = ["__version__"]


# VAD Plugins
AvatarModulePlugin.register(
    AvatarModule.VOICE_VAD,
    "silero",
    SileroVADPlugin(),
)

# STT Plugins
AvatarModulePlugin.register(
    AvatarModule.VOICE_STT,
    "openai_realtime",
    OpenAIRealtimeSTTPlugin(),
)
AvatarModulePlugin.register(
    AvatarModule.VOICE_STT,
    "openai_segment",
    OpenAISegmentSTTPlugin(),
)

# TTS Plugins
AvatarModulePlugin.register(
    AvatarModule.VOICE_TTS,
    "voiceai",
    VoiceAITTSPlugin(__version__, logger),
)

# Inference Runners
InferenceRunner.register(SileroVADRunner)
