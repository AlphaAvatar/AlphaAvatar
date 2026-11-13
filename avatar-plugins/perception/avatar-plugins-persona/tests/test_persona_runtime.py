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
"""Persona profiler lifecycle, Turn acknowledgement and save failures on real runtimes."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from alphaavatar.agents.avatar.provider.base import LLMBase
from alphaavatar.agents.avatar.provider.schemas.model_result import ProviderModelResult
from alphaavatar.agents.persona import PersonaProcessorBase
from alphaavatar.agents.persona.schemas import UserProfile
from alphaavatar.agents.runtime import AvatarRuntime, StateRuntime
from alphaavatar.agents.runtime.modules.foundation import ProviderService
from alphaavatar.agents.runtime.modules.participants import ParticipantRuntime
from alphaavatar.agents.runtime.modules.participants.schemas import ParticipantInput
from alphaavatar.agents.workspace import WorkspacePaths, prepare_session_path, prepare_workspace
from alphaavatar.core.output import OutputRuntime
from alphaavatar.core.perception import PerceptionRuntime
from alphaavatar.core.perception.enums import PerceptionStreamKind
from alphaavatar.core.session import SessionRuntime
from alphaavatar.core.session.enums import IdentityOutcome, IdentitySource
from alphaavatar.core.session.schemas import IdentityRequest
from alphaavatar.core.turn import TurnRuntime, TurnStreamGap
from alphaavatar.core.turn.enums import TurnInputModality
from alphaavatar.core.turn.schemas import TurnEntityRef
from alphaavatar.plugins.persona.cache import DefaultPersonaCache
from alphaavatar.plugins.persona.processors.profiler import ProfilerConfig, ProfilerProcessor
from alphaavatar.plugins.persona.processors.profiler.op import PatchOp, ProfileDelta
from alphaavatar.plugins.persona.runtime import PersonaRuntime
from alphaavatar.plugins.persona.storage import PersonaStore

HANG_GUARD = 30
VDB = "alphaavatar.persona.vdb.lancedb"


class ScriptedLLM(LLMBase):
    def __init__(self, script: Callable[[str], Awaitable[ProfileDelta]]) -> None:
        self.script, self.prompts = script, []

    def validate_input(self, *, require_input_adapter: bool = False) -> None:
        pass

    async def ainvoke_structured(self, model_input, *, output_schema, include_raw=False):
        prompt = "\n".join(item.text or "" for item in model_input.items)
        self.prompts.append(prompt)
        return ProviderModelResult(output=await self.script(prompt))

    async def aclose(self) -> None:
        pass


class ScriptedProviders(ProviderService):
    def __init__(self, script: Callable[[str], Awaitable[ProfileDelta]]) -> None:
        super().__init__()
        self.llm = ScriptedLLM(script)

    def model(self, config):
        self._ensure_open()
        return self.llm


class PersonaInference:
    """In-process stand-in for the Persona VDB runner transport: each user's stored speaker
    vector, if ``speaker_vectors`` has one, and the load of a user it ``holds`` never answering."""

    def __init__(
        self,
        save: bytes | None = b'{"user_id":"x","error":null}',
        *,
        speaker_vectors: dict[str, list[float]] | None = None,
        holds: Callable[[str], bool] = lambda user_id: False,
    ) -> None:
        self.saved: list[dict] = []
        self.operations: list[str] = []
        self._save, self._speaker_vectors, self._holds = save, speaker_vectors or {}, holds

    async def do_inference(self, method: str, data: bytes) -> bytes | None:
        assert method == VDB
        request = json.loads(data)
        self.operations.append(request["op"])
        if request["op"] == "load":
            user_id = request["param"]["user_id"]
            if self._holds(user_id):
                await asyncio.Event().wait()
            vector = self._speaker_vectors.get(user_id)
            return json.dumps(
                {"details_items": [], "speaker_vector": vector, "face_vector": None}
            ).encode()
        self.saved.append(request["param"])
        return self._save

    async def close(self) -> None:
        pass


class BlockingProcessor(PersonaProcessorBase):
    """A slow peer component whose start is still in progress."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.entered, self.finalized = asyncio.Event(), []

    @property
    def name(self) -> str:
        return "blocking"

    async def _start(self) -> None:
        self.entered.set()
        await asyncio.Event().wait()

    async def _stop(self, *, finalize: bool) -> None:
        self.finalized.append(finalize)


async def name_ally(prompt: str) -> ProfileDelta:
    return ProfileDelta(ops=[PatchOp(op="set", path="/name", value="Ally")])


def avatar_runtime(root: Path, providers: ProviderService, inference, **turn) -> AvatarRuntime:
    workspace = WorkspacePaths.from_root(root / "avatar")
    prepare_workspace(workspace)
    session = SessionRuntime(session_id="session")
    session_path = workspace.data.sessions.get("session", date(2026, 11, 2))
    prepare_session_path(session_path)
    perception = PerceptionRuntime(
        session_id="session",
        stream_maxlens=dict.fromkeys(PerceptionStreamKind, 64),
        clock=session.clock,
    )
    turns = TurnRuntime(perception=perception, **turn)
    return AvatarRuntime(
        clock=session.clock,
        workspace=workspace,
        session_path=session_path,
        session=session,
        perception=perception,
        turn=turns,
        output=OutputRuntime(session_id="session", clock=session.clock),
        state=StateRuntime(),
        participants=ParticipantRuntime(session=session, workspace=workspace, turn=turns),
        inference=inference,
        foundation=SimpleNamespace(provider=providers, aclose=providers.aclose),
    )


def persona_for(runtime: AvatarRuntime, *extra: type[PersonaProcessorBase]):
    persona = PersonaRuntime(
        runtime=runtime, store=PersonaStore(runtime=runtime, inference_method=VDB)
    )
    config = ProfilerConfig.model_validate(
        {
            "provider": {
                "gateway": {
                    "trace": {"enabled": False},
                    "tasks": {"persona.profile_delta": {"model": "m"}},
                }
            }
        }
    )
    processors = [ProfilerProcessor(runtime=runtime, persona=persona, config=config)]
    processors.extend(processor(runtime=runtime, persona=persona) for processor in extra)
    persona.bind_processors(processors)
    return persona, processors


def join(runtime: AvatarRuntime, *texts: str):
    participant = runtime.participants.join(user_id="alice", primary=True)
    actor = TurnEntityRef(
        participant_id=participant.participant_id,
        user_id=participant.user_id,
        identity_revision=participant.identity_revision,
    )
    for index, text in enumerate(texts):
        runtime.turn.commit_input(
            input_id=f"input-{index}", modality=TurnInputModality.TEXT, text=text, actors=(actor,)
        )
    return participant


async def wait_until(condition: Callable[[], bool], failure: str) -> None:
    try:
        async with asyncio.timeout(HANG_GUARD):
            while not condition():
                await asyncio.sleep(0.001)
    except TimeoutError:
        pytest.fail(failure, pytrace=False)


def runtime_state_file(runtime: AvatarRuntime) -> Path:
    return runtime.workspace.users.get("alice").runtime_dir / "runtime_state.md"


async def test_turn_gap_is_never_acknowledged_or_profiled(tmp_path: Path) -> None:
    providers = ScriptedProviders(name_ally)
    runtime = avatar_runtime(tmp_path, providers, PersonaInference(), event_maxlen=2)
    persona, _ = persona_for(runtime)
    join(runtime, *(f"fact {index}" for index in range(5)))
    stream = runtime.turn.events

    def consumer_failed() -> bool:
        try:
            stream.read_pending(consumer_id=ProfilerProcessor.CONSUMER_ID)
        except RuntimeError:
            return True
        return False

    await persona.on_start()
    await wait_until(consumer_failed, "The Persona Turn gap was never reported")
    assert stream.consumer_cursor(ProfilerProcessor.CONSUMER_ID) == 0
    with pytest.raises(ExceptionGroup) as stopped:
        await persona.on_stop()
    assert stopped.group_contains(TurnStreamGap)
    # Partial history is neither acknowledged nor turned into profile facts.
    assert stream.consumer_cursor(ProfilerProcessor.CONSUMER_ID) == 0
    assert providers.llm.prompts == []
    await runtime.aclose()


@pytest.mark.parametrize("stop", ["normal", "cancelled-start", "same-tick"])
async def test_only_a_completed_start_finalizes_profiles_and_saves(
    stop: str, tmp_path: Path
) -> None:
    providers, inference = ScriptedProviders(name_ally), PersonaInference()
    runtime = avatar_runtime(tmp_path, providers, inference)
    extra = (BlockingProcessor,) if stop == "cancelled-start" else ()
    persona, processors = persona_for(runtime, *extra)
    participant = join(runtime, "please call me Ally")

    if stop == "normal":
        await persona.on_start()
        await wait_until(
            lambda: len(persona.cache_for(participant.participant_id).turns) == 1,
            "The profiler never recorded the Turn",
        )
        await persona.on_stop()
        (prompt,) = providers.llm.prompts
        assert "please call me Ally" in prompt
        (saved,) = inference.saved
        assert [item["metadata"]["path"] for item in saved["details_items"]] == ["/name"]
        assert runtime_state_file(runtime).is_file()
    else:
        if stop == "cancelled-start":
            starting = asyncio.create_task(persona.on_start())
            async with asyncio.timeout(HANG_GUARD):
                await processors[1].entered.wait()
            starting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await starting
            assert processors[1].finalized == [False]
        else:
            # Close is requested in the same tick as start; it wins without finalization.
            starting = asyncio.create_task(persona.on_start())
            stopping = asyncio.create_task(persona.on_stop())
            with pytest.raises(asyncio.CancelledError):
                await starting
            await stopping
        await persona.on_stop()
        assert providers.llm.prompts == [] and inference.saved == []
        assert not runtime_state_file(runtime).exists()
        with pytest.raises(RuntimeError, match="closing or closed"):
            await persona.on_start()
    assert not any(processor.started for processor in processors)
    await runtime.aclose()


async def test_profile_delta_is_discarded_when_a_provider_swallows_cancellation(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()

    async def swallow(prompt: str) -> ProfileDelta:
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass  # A misbehaving provider SDK returns a value after cancellation.
        return ProfileDelta(ops=[PatchOp(op="set", path="/name", value="Mallory")])

    inference = PersonaInference()
    runtime = avatar_runtime(tmp_path, ScriptedProviders(swallow), inference)
    persona, (profiler,) = persona_for(runtime)
    participant = join(runtime, "my name is Mallory")
    await persona.on_start()
    cache = persona.cache_for(participant.participant_id)
    await wait_until(lambda: len(cache.turns) == 1, "The profiler never recorded the Turn")

    stopping = asyncio.create_task(profiler.stop(finalize=True))
    async with asyncio.timeout(HANG_GUARD):
        await entered.wait()
    stopping.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stopping
    assert cache.profile_details is None and not cache.detail_fields

    await persona.on_stop()
    assert inference.saved == [] and not profiler.started
    await runtime.aclose()


@pytest.mark.parametrize("consumer", ["before-start", "running"])
@pytest.mark.parametrize("resolution", ["perception", "agent"])
async def test_turn_committed_before_identity_resolution_is_profiled_for_the_resolved_user(
    consumer: str, resolution: str, tmp_path: Path
) -> None:
    providers, inference = ScriptedProviders(name_ally), PersonaInference()
    runtime = avatar_runtime(tmp_path, providers, inference)
    persona, _ = persona_for(runtime)
    if consumer == "running":
        await persona.on_start()
    newcomer = runtime.participants.join(primary=True)  # A generated, unresolved user.
    actor = TurnEntityRef(
        participant_id=newcomer.participant_id,
        user_id=newcomer.user_id,
        identity_revision=newcomer.identity_revision,
    )
    runtime.turn.commit_input(
        input_id="input-0",
        modality=TurnInputModality.TEXT,
        text="please call me Ally",
        actors=(actor,),
    )
    # The identity resolves in the same tick, so the profiler can only consume afterwards.
    if resolution == "perception":
        outcome = runtime.participants.bind_user(
            IdentityRequest(
                participant_id=newcomer.participant_id,
                user_id="alice",
                source=IdentitySource.PERCEPTION,
                expected_revision=newcomer.identity_revision,
                reason="Voice matched the stored user",
            )
        )
        assert outcome == IdentityOutcome.APPLIED
    else:
        result = await runtime.participants.invoke(
            ParticipantInput(user_id="alice", reason="The speaker said they are Alice"),
            input_id="input-0",
        )
        assert result["outcome"] == IdentityOutcome.APPLIED.value
    stream = runtime.turn.events
    assert stream.consumer_cursor(ProfilerProcessor.CONSUMER_ID) == 0
    if consumer == "before-start":
        await persona.on_start()
    cache = persona.cache_for(newcomer.participant_id)
    await wait_until(lambda: len(cache.turns) == 1, "The pre-resolution Turn was never recorded")
    await persona.on_stop()

    # Not skipped: the Turn is profiled for the participant's resolved user and saved there.
    (prompt,) = providers.llm.prompts
    assert "please call me Ally" in prompt
    (saved,) = inference.saved
    assert saved["user_id"] == "alice"
    assert [item["metadata"]["path"] for item in saved["details_items"]] == ["/name"]
    assert runtime_state_file(runtime).is_file()
    assert not runtime.workspace.users.get(newcomer.user_id).root.exists()
    # The committed Turn keeps the identity it was accepted with.
    (frozen,) = runtime.turn.get("input-0").actors
    assert (frozen.user_id, frozen.identity_revision) == (newcomer.user_id, 0)
    await runtime.aclose()


@pytest.mark.parametrize(
    "people",
    [("alice",), ("alice", "alice"), ("alice", "bob"), ("alice", None)],
    ids=["one-user", "one-user-twice", "two-users", "known-and-unknown"],
)
async def test_a_turns_private_profile_needs_its_every_actor_to_be_one_accepted_user(
    people: tuple[str | None, ...], tmp_path: Path
) -> None:
    runtime = avatar_runtime(tmp_path, ScriptedProviders(name_ally), PersonaInference())
    persona, _ = persona_for(runtime)
    actors = []
    for user in people:
        if user is None:  # An unattributed segment: heard through the device, nobody's.
            actors.append(TurnEntityRef(kind="person", device_id="phone-1"))
            continue
        participant = runtime.participants.join(user_id=user)
        actors.append(
            TurnEntityRef(
                participant_id=participant.participant_id,
                user_id=participant.user_id,
                identity_revision=participant.identity_revision,
            )
        )
    snapshot = runtime.turn.commit_input(
        input_id="input-0", modality=TurnInputModality.TEXT, text="hello", actors=tuple(actors)
    )

    shown = persona.content_for(snapshot)
    # One user, if across two participants: theirs. Anyone else in the Turn: nobody's.
    assert ("alice" in shown) == (set(people) == {"alice"})
    assert "bob" not in shown
    await runtime.aclose()


@pytest.mark.parametrize(
    "result",
    [b'{"user_id":"alice","inserted":0,"error":"disk full"}', b"", None],
    ids=["error-field", "empty", "none"],
)
async def test_vdb_save_failure_surfaces_instead_of_silently_succeeding(
    result: bytes | None, tmp_path: Path
) -> None:
    runtime = avatar_runtime(tmp_path, ScriptedProviders(name_ally), PersonaInference(save=result))
    participant = join(runtime)
    cache = DefaultPersonaCache(participant=participant)
    cache.set_base(UserProfile())  # Its load found none stored, so the save writes the voice.
    cache.add_speaker_vector(np.ones(192, dtype=np.float32), 3.0)
    store = PersonaStore(runtime=runtime, inference_method=VDB)
    with pytest.raises(ExceptionGroup) as failed:
        await store.save(persona=cache)
    assert failed.group_contains(RuntimeError, match="Persona VDB save")
    await runtime.aclose()


def unit(*values: float) -> np.ndarray:
    vector = np.asarray(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def merged(loaded: np.ndarray, voice: np.ndarray) -> np.ndarray:
    """A save's rule: 0.95 of the vector loaded for the user, 0.05 of the session's voice."""
    return unit(*(0.95 * loaded + 0.05 * voice))


@pytest.mark.parametrize("stored", ["vector", "none", "unloaded", "new-user"])
async def test_a_save_merges_the_sessions_voice_into_the_stored_speaker_vector_loaded_for_its_user(
    stored: str, tmp_path: Path
) -> None:
    stored_vector = unit(1, 0, 0, 0)
    unloaded = stored in ("unloaded", "new-user")
    inference = PersonaInference(
        speaker_vectors={"alice": stored_vector.tolist()} if stored == "vector" else {},
        holds=lambda user_id: unloaded,
    )
    runtime = avatar_runtime(tmp_path, ScriptedProviders(name_ally), inference)
    persona, _ = persona_for(runtime)
    # A new user is one the session allocates itself; alice is the application's.
    participant = runtime.participants.join(primary=True) if stored == "new-user" else join(runtime)
    await persona.on_start()
    if not unloaded:
        await persona.load_profile(participant_id=participant.participant_id)
    cache = persona.cache_for(participant.participant_id)
    first, second = unit(0, 1, 0, 0), unit(0, 0, 1, 0)
    cache.add_speaker_vector(first, 1.0)
    cache.add_speaker_vector(second, 3.0)

    # While it runs, the session's voice stays its own: the stored speaker vector is not in it.
    voice = unit(*(1.0 * first + 3.0 * second))
    assert cache.speaker_vector == pytest.approx(voice)
    await persona.on_stop()

    saved = [s["speaker_vector"] for s in inference.saved if s["user_id"] == participant.user_id]
    if stored == "vector":
        assert saved == [pytest.approx(merged(stored_vector, voice))]
    elif stored in ("none", "new-user"):  # None stored, read or known: the session's voice.
        assert saved == [pytest.approx(voice)]
    else:  # The stored speaker vector was never read, so the save leaves it as it is.
        assert saved == []
    await runtime.aclose()


@pytest.mark.parametrize("load", ["loaded", "unloaded"])
async def test_a_rebound_participant_saves_into_its_new_users_stored_speaker_vector_alone(
    load: str, tmp_path: Path
) -> None:
    alice, bob = unit(1, 0, 0, 0), unit(0, 1, 0, 0)
    inference = PersonaInference(
        speaker_vectors={"alice": alice.tolist(), "bob": bob.tolist()},
        holds=lambda user_id: load == "unloaded" and user_id == "bob",
    )
    runtime = avatar_runtime(tmp_path, ScriptedProviders(name_ally), inference)
    persona, _ = persona_for(runtime)
    participant = join(runtime)
    await persona.on_start()
    await persona.load_profile(participant_id=participant.participant_id)
    outcome = runtime.participants.bind_user(
        IdentityRequest(
            participant_id=participant.participant_id,
            user_id="bob",
            source=IdentitySource.PERCEPTION,
            expected_revision=participant.identity_revision,
            reason="Voice matched the stored user",
        )
    )
    assert outcome == IdentityOutcome.APPLIED
    if load == "loaded":
        await persona.load_profile(participant_id=participant.participant_id)
    voice = unit(0, 0, 1, 0)
    persona.cache_for(participant.participant_id).add_speaker_vector(voice, 3.0)
    await persona.on_stop()

    # Alice's stored speaker vector, loaded first, never takes in what is saved as Bob.
    saved = {save["user_id"]: save["speaker_vector"] for save in inference.saved}
    if load == "loaded":
        assert saved == {"bob": pytest.approx(merged(bob, voice))}
    else:
        assert saved == {}
    await runtime.aclose()


@pytest.mark.parametrize("stored", ["vector", "none"])
async def test_participants_of_one_user_save_one_voice_of_all_their_speech(
    stored: str, tmp_path: Path
) -> None:
    stored_vector = unit(1, 0, 0, 0)
    inference = PersonaInference(
        speaker_vectors={"alice": stored_vector.tolist()} if stored == "vector" else {}
    )
    runtime = avatar_runtime(tmp_path, ScriptedProviders(name_ally), inference)
    persona, _ = persona_for(runtime)
    await persona.on_start()
    # One voice heard as two of alice's participants, and bob's own.
    heard = (
        ("alice", [(unit(0, 1, 0, 0), 3.0), (unit(0, 0, 1, 0), 0.5)]),
        ("alice", [(unit(0, 1, 1, 0), 1.0)]),
        ("bob", [(unit(0, 0, 0, 1), 3.0)]),
    )
    for user, segments in heard:
        participant = runtime.participants.join(user_id=user)
        await persona.load_profile(participant_id=participant.participant_id)
        for vector, seconds in segments:
            persona.cache_for(participant.participant_id).add_speaker_vector(vector, seconds)
    await persona.on_stop()

    # Each of alice's writes carries all of her speech, so whichever lands last, it is the same.
    alice = unit(*(3.0 * unit(0, 1, 0, 0) + 0.5 * unit(0, 0, 1, 0) + 1.0 * unit(0, 1, 1, 0)))
    written = {
        user: [s["speaker_vector"] for s in inference.saved if s["user_id"] == user]
        for user in ("alice", "bob")
    }
    expected = merged(stored_vector, alice) if stored == "vector" else alice
    assert written == {
        "alice": [pytest.approx(expected)] * 2,
        "bob": [pytest.approx(unit(0, 0, 0, 1))],
    }
    await runtime.aclose()
