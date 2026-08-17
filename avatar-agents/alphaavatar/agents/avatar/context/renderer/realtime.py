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
from dataclasses import replace

from alphaavatar.agents.avatar.context.schema import ContextBuildRequest, ContextBuildResult
from alphaavatar.agents.providers.schema import RealtimeModelInput


class RealtimeRenderer:
    def render(self, request: ContextBuildRequest) -> ContextBuildResult:
        return ContextBuildResult(
            model_input=replace(
                request.base_input.remove(request.input_id),
                realtime=RealtimeModelInput(
                    alignment=request.alignment,
                    visual_selection=request.visual_selection,
                    direct_inputs=request.alignment.direct_inputs,
                ),
            )
        )
