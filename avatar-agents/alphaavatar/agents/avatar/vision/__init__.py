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

from alphaavatar.agents.avatar.vision.base import NoopVision, VisionBase
from alphaavatar.agents.avatar.vision.realtime import RealtimeVision
from alphaavatar.agents.avatar.vision.sampled_frame import SampledFrameVision


def build_vision(agent) -> VisionBase:
    vision_config = agent.avatar_config.vision_plugin_config

    if not vision_config.vision_input_enabled:
        return NoopVision(agent)

    if vision_config.use_sampled_frame_input:
        return SampledFrameVision(agent)

    if vision_config.use_realtime_video_input:
        return RealtimeVision(agent)

    return NoopVision(agent)


__all__ = [
    "VisionBase",
    "NoopVision",
    "SampledFrameVision",
    "RealtimeVision",
    "build_vision",
]
