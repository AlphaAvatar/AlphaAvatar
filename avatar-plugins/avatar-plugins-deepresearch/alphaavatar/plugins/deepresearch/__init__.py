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
from alphaavatar.agents import AvatarModule, AvatarPlugin

from .log import logger
from .tavily import TavilyDeepResearchTool
from .version import __version__

__all__ = [
    "__version__",
]


class TavilyPlugin(AvatarPlugin):
    def __init__(self) -> None:
        super().__init__(__name__, __version__, __package__, logger)  # type: ignore

    def download_files(self): ...

    def get_plugin(
        self,
        *args,
        **kwargs,
    ) -> TavilyDeepResearchTool:
        try:
            return TavilyDeepResearchTool(*args, **kwargs)
        except Exception:
            raise ImportError(
                "The 'tavily[default]' DeepResearch plugin is required but is not installed.\n"
                "To fix this, install the optional dependency: `pip install alphaavatar-plugins-deepresearch`"
            )


# plugin init
AvatarPlugin.register_avatar_plugin(AvatarModule.DEEPRESEARCH, "default", TavilyPlugin())
