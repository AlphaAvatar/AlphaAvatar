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
"""Context prefixes are pinned to an accepted identity; canonical history is never rewritten."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from alphaavatar.agents.avatar.context import ContextIdentityChanged, ContextManager
from alphaavatar.agents.avatar.context.schemas import ContextPrepareRequest
from alphaavatar.agents.avatar.provider.enums import ModelRole
from alphaavatar.agents.avatar.provider.records import model_record_batch
from alphaavatar.agents.avatar.provider.schemas import ModelInput, ModelInputMessage, ModelTextPart
from alphaavatar.agents.configs import AvatarConfig
from alphaavatar.agents.runtime import AvatarRuntime, StateRuntime
from alphaavatar.agents.runtime.inference import InferenceExecutor
from alphaavatar.core.output.schemas import OutputScope
from alphaavatar.core.session import (
    IdentityOutcome,
    IdentityRequest,
    IdentitySource,
    SessionRuntime,
)
from alphaavatar.core.turn.enums import TurnInputModality
from alphaavatar.core.turn.schemas import TurnEntityRef, TurnSnapshot
from alphaavatar.core.workspace import WorkspacePaths


class UserScopedSource:
    """Persona/Memory stand-in rendering whichever identity the Context asks for."""

    def __init__(self, runtime: AvatarRuntime) -> None:
        self._runtime = runtime

    def content_for(self, snapshot: TurnSnapshot) -> str:
        actors = self._runtime.participants.project_turn(snapshot).actors
        return " ".join(f"profile-of-{actor.user_id}" for actor in actors)


def runtime_with_context(tmp_path: Path) -> tuple[AvatarRuntime, ContextManager]:
    config = AvatarConfig.model_validate({"avatar": {"id": "avatar-1"}})
    workspace = WorkspacePaths.from_root(tmp_path / "workspace")
    runtime = AvatarRuntime.create(
        workspace=workspace,
        session=SessionRuntime(session_id="session-1"),
        session_path=workspace.data.sessions.get("session-1", date(2026, 1, 1)),
        state=StateRuntime(),
        config=config.runtime,
        inference=InferenceExecutor(str(tmp_path / "unused.sock")),
    )
    context = config.context.get_plugin(runtime=runtime, avatar_config=config)
    source = UserScopedSource(runtime)
    context.bind_sources(memory=source, persona=source)
    return runtime, context


def commit(runtime: AvatarRuntime, input_id: str, text: str) -> TurnSnapshot:
    person = runtime.session.primary_participant
    return runtime.turn.commit_input(
        input_id=input_id,
        modality=TurnInputModality.TEXT,
        text=text,
        actors=(
            TurnEntityRef(
                kind="person",
                participant_id=person.participant_id,
                identity_sequence=person.identity_sequence,
                user_id=person.user_id,
            ),
        ),
        context_ids=(runtime.state.context_id,),
    )


async def prepare(context: ContextManager, turn: TurnSnapshot, context_id: str) -> ModelInput:
    return await context.prepare(
        ContextPrepareRequest(
            input=context.accept_turn(turn),
            turn_id=turn.turn_id,
            context_id=context_id,
            input_id=turn.input_id,
        )
    )


def texts(model_input: ModelInput) -> list[str]:
    return [item.text or "" for item in model_input.items if isinstance(item, ModelInputMessage)]


async def test_identity_correction_rebuilds_the_prefix_but_keeps_accepted_history(
    tmp_path: Path,
) -> None:
    runtime, context = runtime_with_context(tmp_path)
    context_id = runtime.state.context_id
    try:
        person = runtime.participants.join(user_id="user-b", primary=True)
        first = commit(runtime, "input-1", "My name is B.")
        prefix = await prepare(context, first, context_id)
        reply = ModelInputMessage(
            id="reply-1", role=ModelRole.ASSISTANT, parts=(ModelTextPart("Hello B."),)
        )
        runtime.output.publish_records(
            model_record_batch(
                batch_id="batch-1",
                source="test.loop",
                scope=OutputScope(context_id, first.turn_id, "run-1"),
                items=(reply,),
                identity_basis=runtime.participants.identity_basis(first),
            )
        )
        assert "profile-of-user-b" in texts(prefix)[0]

        outcome = runtime.participants.bind_user(
            IdentityRequest(
                participant_id=person.participant_id,
                user_id="user-a",
                source=IdentitySource.PERCEPTION,
                basis_sequence=0,
                reason="Face recognition matched user-a",
            )
        )
        assert outcome is IdentityOutcome.APPLIED
        # A prefix captured for B cannot carry a continuation after the correction.
        with pytest.raises(ContextIdentityChanged):
            context.build(prefix)

        second = commit(runtime, "input-2", "What did you call me?")
        current = await prepare(context, second, context_id)
        system, *history, turn_input = texts(current)
        assert "profile-of-user-a" in system and "profile-of-user-b" not in system
        # B's accepted turn and the reply already given stay in canonical history verbatim.
        assert history == ["My name is B.", "Hello B."]
        assert 'input_id="input-2"' in turn_input
        assert context.build(current).items == current.items
        assert runtime.turn.get("input-1").actors == first.actors
        assert first.actors[0].user_id == "user-b"
    finally:
        await context.aclose()
        await runtime.aclose()
