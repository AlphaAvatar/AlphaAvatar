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
from typing import Any

from alphaavatar.agents.providers import ProviderGateway

from ...profile import UserProfileDetails
from .config import ProfilerProviderConfig
from .op import ProfileDelta
from .prompt import DELTA_PROMPT


class ProfilerProvider:
    def __init__(self, config: ProfilerProviderConfig) -> None:
        self._task = config.profile_delta_task
        self._gateway = ProviderGateway(config.gateway)
        self._gateway.validate_tasks([self._task])

    async def extract(
        self,
        *,
        profile_details_dump: dict[str, Any],
        new_turn: str,
        metadata: dict[str, Any],
    ) -> ProfileDelta:
        result = await self._gateway.ainvoke_structured(
            task_name=self._task,
            prompt=DELTA_PROMPT,
            payload={
                "current_profile": profile_details_dump,
                "profile_reference": UserProfileDetails.field_descriptions_prompt(),
                "new_turn": new_turn,
            },
            output_schema=ProfileDelta,
            metadata=metadata,
        )
        return (
            result.output
            if isinstance(result.output, ProfileDelta)
            else ProfileDelta.model_validate(result.output)
        )
