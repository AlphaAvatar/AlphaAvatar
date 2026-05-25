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
from .sink import CompositeStatusSink, LiveKitDataChannelStatusSink, LoggerStatusSink
from .version import __version__

__all__ = [
    "__version__",
    "DefaultStatusPolicy",
    "DefaultStatusRenderer",
    "CompositeStatusSink",
    "LoggerStatusSink",
    "LiveKitDataChannelStatusSink",
]


class DefaultStatusPlugin(AvatarPlugin):
    def __init__(self) -> None:
        super().__init__(__name__, __version__, __package__, logger)  # type: ignore

    def download_files(self): ...

    def get_plugin(
        self,
        *,
        default_language: str = "en",
        enable_llm_renderer: bool = False,
        enabled: bool = True,
        enable_logger_sink: bool = True,
        enable_livekit_data_sink: bool = False,
        livekit_data_topic: str = "agent.status",
        **kwargs,
    ) -> StatusEmitter:
        renderer = DefaultStatusRenderer(
            default_language=default_language,
            enable_llm=enable_llm_renderer,
        )
        policy = DefaultStatusPolicy()

        sinks = []

        if enable_logger_sink:
            sinks.append(LoggerStatusSink())

        if enable_livekit_data_sink:
            sinks.append(
                LiveKitDataChannelStatusSink(
                    topic=livekit_data_topic,
                )
            )

        sink = CompositeStatusSink(sinks)

        return StatusEmitter(
            sink=sink,
            renderer=renderer,
            policy=policy,
            enabled=enabled,
        )


AvatarPlugin.register_avatar_plugin(AvatarModule.STATUS, "default", DefaultStatusPlugin())
