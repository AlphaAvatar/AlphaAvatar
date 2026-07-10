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

from dataclasses import dataclass

from alphaavatar.core.perception import PerceptionRuntime

from .context_runtime import ContextRuntime
from .session_runtime import SessionRuntime


@dataclass(slots=True, frozen=True)
class AvatarRuntime:
    """
    Session-scoped runtime composition root.

    This class only owns references. It does not manage plugins or RTC.
    """

    session: SessionRuntime
    context: ContextRuntime
    perception: PerceptionRuntime

    def __post_init__(self) -> None:
        if self.session.session_id != self.perception.session_id:
            raise ValueError(
                "SessionRuntime and PerceptionRuntime session IDs differ: "
                f"session={self.session.session_id!r}, "
                f"perception={self.perception.session_id!r}"
            )

    @classmethod
    def create(
        cls,
        *,
        session: SessionRuntime,
        context: ContextRuntime,
    ) -> AvatarRuntime:
        return cls(
            session=session,
            context=context,
            perception=PerceptionRuntime(
                session_id=session.session_id,
            ),
        )
