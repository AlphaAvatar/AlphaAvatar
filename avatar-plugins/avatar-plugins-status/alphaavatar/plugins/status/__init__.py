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
from alphaavatar.agents.status import StatusEmitter

from .log import logger
from .policy import DefaultStatusPolicy
from .renderer import DefaultStatusRenderer
from .sink import (
    CompositeStatusSink,
    LoggerStatusSink,
    StatusActionEventSink,
    TextOrVoiceStatusSink,
)
from .version import __version__

__all__ = [
    "__version__",
    "DefaultStatusPolicy",
    "DefaultStatusRenderer",
    "CompositeStatusSink",
    "LoggerStatusSink",
    "StatusActionEventSink",
    "TextOrVoiceStatusSink",
]


class DefaultStatusPlugin(AvatarPlugin):
    def __init__(self) -> None:
        super().__init__(__name__, __version__, __package__, logger)  # type: ignore

    def download_files(self): ...

    def get_plugin(
        self,
        *,
        enabled: bool = True,
        action_topic: str = "agent.status.action",
        text_topic: str = "agent.status.text",
        **kwargs,
    ) -> StatusEmitter:
        renderer = DefaultStatusRenderer()
        policy = DefaultStatusPolicy()

        sink = CompositeStatusSink(
            [
                # Always enabled for observability.
                LoggerStatusSink(),
                # Emits structured action events.
                # The sink itself becomes useful only when a LiveKit room exists.
                StatusActionEventSink(
                    topic=action_topic,
                ),
                # Automatically chooses text or voice based on interaction_method.
                TextOrVoiceStatusSink(
                    text_topic=text_topic,
                ),
            ]
        )

        return StatusEmitter(
            sink=sink,
            renderer=renderer,
            policy=policy,
            enabled=enabled,
        )


AvatarPlugin.register_avatar_plugin(AvatarModule.STATUS, "default", DefaultStatusPlugin())
