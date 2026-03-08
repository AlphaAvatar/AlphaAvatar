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

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from alphaavatar.agents.log import logger

from .room_type import RoomType


@dataclass
class ChannelAdapterBuilder:
    build_ingress: Callable[..., Any] | None = None
    build_egress: Callable[..., Any] | None = None


_CHANNEL_ADAPTER_BUILDERS: dict[RoomType, ChannelAdapterBuilder] = {}


def register_channel_adapters(
    room_type: RoomType,
    *,
    build_ingress=None,
    build_egress=None,
) -> None:
    if room_type in _CHANNEL_ADAPTER_BUILDERS:
        logger.warning(
            "Channel adapters already registered for room_type=%s, overriding", room_type
        )

    _CHANNEL_ADAPTER_BUILDERS[room_type] = ChannelAdapterBuilder(
        build_ingress=build_ingress,
        build_egress=build_egress,
    )


def get_channel_adapters_builder(room_type: RoomType) -> ChannelAdapterBuilder | None:
    return _CHANNEL_ADAPTER_BUILDERS.get(room_type)
