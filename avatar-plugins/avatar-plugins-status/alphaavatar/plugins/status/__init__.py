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
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.status import StatusEmitter

from .log import logger
from .policy import DefaultStatusPolicy
from .renderer import DefaultStatusRenderer
from .sink import (
    CompositeStatusSink,
    LoggerStatusSink,
    RuntimeStatusSink,
    StatusVoiceOutput,
)
from .version import __version__

__all__ = [
    "__version__",
    "DefaultStatusPolicy",
    "DefaultStatusRenderer",
    "CompositeStatusSink",
    "LoggerStatusSink",
    "RuntimeStatusSink",
    "StatusVoiceOutput",
]


class DefaultStatusPlugin(AvatarPlugin):
    def __init__(self) -> None:
        super().__init__(__name__, __version__, __package__, logger)

    def download_files(self):
        return None

    def get_plugin(
        self,
        *,
        runtime: AvatarRuntime,
        enabled: bool = True,
        **kwargs,
    ) -> StatusEmitter:
        renderer = DefaultStatusRenderer()
        policy = DefaultStatusPolicy()

        sink = CompositeStatusSink(
            [
                LoggerStatusSink(),
                StatusVoiceOutput(
                    runtime=runtime,
                ),
                RuntimeStatusSink(
                    runtime=runtime,
                ),
            ]
        )

        return StatusEmitter(
            renderer=renderer,
            policy=policy,
            sink=sink,
            enabled=enabled,
        )


AvatarPlugin.register_avatar_plugin(
    AvatarModule.STATUS,
    "default",
    DefaultStatusPlugin(),
)
