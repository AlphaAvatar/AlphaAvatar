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
from __future__ import annotations

import os

from livekit import api, rtc
from livekit.agents import (
    NOT_GIVEN,
    AgentSession,
    NotGivenOr,
)
from livekit.agents.types import ATTRIBUTE_PUBLISH_ON_BEHALF

from alphaavatar.agents.sessions import VirtialCharacterSession

from ..log import logger
from .config import AiriConfig
from .process import AiriProcess

_AVATAR_IDENTITY = "airi-avatar-worker"


class AiriCharacterSession(VirtialCharacterSession):
    def __init__(self, avatar_config: AiriConfig):
        self._avatar_config = avatar_config
        self._avatar_participant_identity = _AVATAR_IDENTITY

        self._airi_proc = AiriProcess(
            repo_dir=avatar_config.airi_repo_dir,
            port=avatar_config.airi_dev_port,
        )

    async def start(
        self,
        agent_identity: str,
        agent_session: AgentSession,
        room: rtc.Room,
        *,
        livekit_url: NotGivenOr[str] = NOT_GIVEN,
        livekit_api_key: NotGivenOr[str] = NOT_GIVEN,
        livekit_api_secret: NotGivenOr[str] = NOT_GIVEN,
    ) -> None:
        attrs = dict(room.local_participant.attributes)
        attrs["lk.publish_on_behalf"] = agent_identity
        await room.local_participant.set_attributes(attrs)

        livekit_url = livekit_url or (os.getenv("LIVEKIT_URL") or NOT_GIVEN)
        livekit_api_key = livekit_api_key or (os.getenv("LIVEKIT_API_KEY") or NOT_GIVEN)
        livekit_api_secret = livekit_api_secret or (os.getenv("LIVEKIT_API_SECRET") or NOT_GIVEN)
        if not livekit_url or not livekit_api_key or not livekit_api_secret:
            raise ValueError(
                "livekit_url, livekit_api_key, and livekit_api_secret must be set "
                "by arguments or environment variables"
            )

        # Prepare attributes for JWT token
        attributes: dict[str, str] = {
            ATTRIBUTE_PUBLISH_ON_BEHALF: agent_identity,
        }

        livekit_token = (
            api.AccessToken(api_key=livekit_api_key, api_secret=livekit_api_secret)
            .with_kind("agent")
            .with_identity(self._avatar_participant_identity)
            .with_grants(api.VideoGrants(room_join=True, room=room.name))
            # allow the avatar agent to publish audio and video on behalf of your local agent
            .with_attributes(attributes)
            .to_jwt()
        )

        logger.debug("starting avatar session")
        await self._airi_proc.start(
            livekit_url=livekit_url,
            livekit_token=livekit_token,
            agent_identity=agent_identity,
            avatar_identity=self._avatar_participant_identity,
        )
