# Copyright 2025 AlphaAvatar project
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
import importlib.util

from .avatar_config import AvatarConfig
from .avatar_info_config import AvatarInfoConfig
from .livekit_plugin_config import LiveKitPluginConfig
from .memory_plugin_config import MemoryConfig
from .parser import get_avatar_args, read_args
from .session_config import SessionConfig

__all__ = [
    "SessionConfig",
    "AvatarConfig",
    "LiveKitPluginConfig",
    "MemoryConfig",
    "AvatarInfoConfig",
    "read_args",
    "get_avatar_args",
]


def prewarm_import():
    english_spec = importlib.util.find_spec("livekit.plugins.turn_detector.english")
    multilingual_spec = importlib.util.find_spec("livekit.plugins.turn_detector.multilingual")

    if english_spec is not None:
        importlib.import_module("livekit.plugins.turn_detector.english")
    if multilingual_spec is not None:
        importlib.import_module("livekit.plugins.turn_detector.multilingual")


prewarm_import()
