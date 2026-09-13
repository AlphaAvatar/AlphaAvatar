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

from alphaavatar.agents import AvatarPlugin
from alphaavatar.agents.persona import PersonaBase
from alphaavatar.agents.runtime import AvatarRuntime

from ...log import logger
from ...version import __version__
from .analysis_runner import FaceAnalysisRunner
from .processor import FaceProcessor


class FacePlugin(AvatarPlugin):
    def __init__(self) -> None:
        super().__init__(__name__, __version__, __package__, logger)  # type: ignore

    def get_plugin(
        self,
        *,
        runtime: AvatarRuntime,
        persona: PersonaBase,
        init_config: dict[str, Any],
        **kwargs: Any,
    ) -> FaceProcessor:
        return FaceProcessor(
            runtime=runtime,
            persona=persona,
            **init_config,
        )


__all__ = ["FaceAnalysisRunner", "FacePlugin"]
