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

from alphaavatar.agents.avatar.turn_controller import AvatarTurnSink
from alphaavatar.agents.router import TurnTakingDecision
from alphaavatar.agents.runtime import TurnSnapshot
from livekit.agents import AgentSession, llm


class LiveKitTurnResponseSink(AvatarTurnSink):
    def __init__(
        self,
        *,
        session_provider: Callable[[], AgentSession],
    ) -> None:
        self._session_provider = session_provider
        self._submitted_inputs: set[str] = set()

    async def submit_turn(
        self,
        snapshot: TurnSnapshot,
        decision: TurnTakingDecision,
    ) -> None:
        if snapshot.input_id in self._submitted_inputs:
            return
        if not snapshot.text:
            raise ValueError("LiveKit reply requires non-empty turn text")

        message = llm.ChatMessage(
            id=snapshot.input_id,
            role="user",
            content=[snapshot.text],
            created_at=snapshot.committed_at.unix_seconds,
            extra={
                "alphaavatar_turn_id": snapshot.turn_id,
                "alphaavatar_turn_candidate_id": decision.turn_candidate_id,
                "alphaavatar_candidate_revision": decision.candidate_revision,
            },
        )

        self._submitted_inputs.add(snapshot.input_id)

        try:
            self._session_provider().generate_reply(
                user_input=message,
                input_modality="audio",
            )
        except Exception:
            self._submitted_inputs.discard(snapshot.input_id)
            raise

    async def interrupt(self, decision: TurnTakingDecision) -> None:
        session = self._session_provider()

        if session.current_speech is None:
            return

        try:
            await session.interrupt(force=True)
        except RuntimeError:
            # Speech may have completed between current_speech and interrupt().
            if session.current_speech is not None:
                raise
