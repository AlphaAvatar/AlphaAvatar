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
"""Session-scoped Avatar runtime composition."""

from __future__ import annotations

from dataclasses import dataclass

from alphaavatar.core.output import OutputRuntime
from alphaavatar.core.perception import PerceptionRuntime

from .context_runtime import ContextRuntime
from .inference import InferenceExecutor
from .session_runtime import SessionRuntime


@dataclass(slots=True, frozen=True)
class AvatarRuntime:
    """
    Session-scoped runtime composition root.

    This class owns runtime references, but does not own transport adapters or
    runtime plugins.
    """

    session: SessionRuntime
    context: ContextRuntime
    perception: PerceptionRuntime
    output: OutputRuntime
    inference: InferenceExecutor

    def __post_init__(self) -> None:
        session_id = self.session.session_id

        if session_id != self.perception.session_id:
            raise ValueError(
                "SessionRuntime and PerceptionRuntime session IDs differ: "
                f"session={session_id!r}, "
                f"perception={self.perception.session_id!r}"
            )

        if session_id != self.output.session_id:
            raise ValueError(
                "SessionRuntime and OutputRuntime session IDs differ: "
                f"session={session_id!r}, "
                f"output={self.output.session_id!r}"
            )

    @classmethod
    def create(
        cls,
        *,
        session: SessionRuntime,
        context: ContextRuntime,
        inference: InferenceExecutor | None = None,
    ) -> AvatarRuntime:
        session_id = session.session_id

        return cls(
            session=session,
            context=context,
            perception=PerceptionRuntime(session_id=session_id),
            output=OutputRuntime(session_id=session_id),
            inference=inference or InferenceExecutor.from_env(),
        )

    async def aclose(self) -> None:
        await self.output.aclose()
        await self.inference.close()
