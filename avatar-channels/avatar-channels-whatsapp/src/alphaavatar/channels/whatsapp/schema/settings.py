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

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class WhatsAppBridgeSettings:
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    identity: str = "whatsapp-bridge"

    @staticmethod
    def from_env() -> WhatsAppBridgeSettings:
        livekit_url = os.environ.get("LIVEKIT_URL", "")
        livekit_api_key = os.environ.get("LIVEKIT_API_KEY", "")
        livekit_api_secret = os.environ.get("LIVEKIT_API_SECRET", "")

        if not livekit_url or not livekit_api_key or not livekit_api_secret:
            raise RuntimeError(
                "Missing LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET in environment. "
                "Run this core under the same environment as AlphaAvatar startup."
            )

        return WhatsAppBridgeSettings(
            livekit_url=livekit_url,
            livekit_api_key=livekit_api_key,
            livekit_api_secret=livekit_api_secret,
        )
