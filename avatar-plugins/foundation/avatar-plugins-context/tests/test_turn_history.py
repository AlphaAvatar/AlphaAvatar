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
"""History keeps each Turn's user message as built, media included. Requests replay it with
historical images marked in place, and carry only the current Turn's runtime context."""

from __future__ import annotations

import base64
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from alphaavatar.agents.avatar.context import ContextManager
from alphaavatar.agents.avatar.context.schemas import ContextPrepareRequest
from alphaavatar.agents.avatar.provider.enums import ModelMediaKind, ModelRole
from alphaavatar.agents.avatar.provider.errors import ModelCapabilityError
from alphaavatar.agents.avatar.provider.records import model_record_batch
from alphaavatar.agents.avatar.provider.schemas import (
    ModelFunctionCall,
    ModelFunctionOutput,
    ModelInput,
    ModelInputMessage,
    ModelMediaPart,
    ModelRequest,
    ModelTextPart,
    ProviderTaskConfig,
)
from alphaavatar.agents.configs import AvatarConfig
from alphaavatar.agents.constants import RUNTIME_CONTEXT_TOOL_NAME
from alphaavatar.agents.runtime import AvatarRuntime, StateRuntime
from alphaavatar.agents.runtime.inference import InferenceExecutor
from alphaavatar.agents.workspace import WorkspacePaths
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.env.schemas import PerceptionSegmentRef
from alphaavatar.core.media import ImagePayload, TextPayload
from alphaavatar.core.media.enums import PayloadFormat, PayloadView
from alphaavatar.core.output.schemas import OutputScope
from alphaavatar.core.perception.enums import MediaModality, MediaSourceKind, MediaSourceState
from alphaavatar.core.perception.schemas import MediaSourceStateEvent
from alphaavatar.core.session import SessionRuntime
from alphaavatar.core.time import RuntimeTimeRange
from alphaavatar.core.turn.enums import TurnInputModality
from alphaavatar.core.turn.schemas import TurnEntityRef, TurnSnapshot
from alphaavatar.plugins.provider.openai.adapters.responses import ResponsesAdapter
from alphaavatar.plugins.provider.openai.llms.config import ResponsesInputConfig

VLM = {"enabled": True, "input_mode": "vlm"}
MARK = {"type": "input_text", "text": "<image_not_replayed />"}


def start(tmp_path: Path, **sections: object) -> tuple[AvatarRuntime, ContextManager]:
    config = AvatarConfig.model_validate({"avatar": {"id": "avatar-1"}, **sections})
    workspace = WorkspacePaths.from_root(tmp_path / "workspace")
    runtime = AvatarRuntime.create(
        workspace=workspace,
        session=SessionRuntime(session_id="session-1"),
        session_path=workspace.data.sessions.get("session-1", date(2026, 1, 1)),
        state=StateRuntime(),
        config=config.runtime,
        inference=InferenceExecutor(str(tmp_path / "unused.sock")),
    )
    runtime.participants.join(user_id="user-1", primary=True)
    return runtime, config.context.get_plugin(runtime=runtime, avatar_config=config)


def actor(runtime: AvatarRuntime) -> TurnEntityRef:
    person = runtime.session.primary_participant
    return TurnEntityRef(
        kind="person",
        participant_id=person.participant_id,
        identity_sequence=person.identity_sequence,
        user_id=person.user_id,
    )


def typed(runtime: AvatarRuntime, input_id: str, text: str) -> TurnSnapshot:
    perception = runtime.perception
    observation = EnvObservation.text_input(
        time_range=RuntimeTimeRange.point(perception.clock.now()),
        source=perception.next_source("keyboard"),
        payload=TextPayload.create(text=text),
    )
    return runtime.turn.commit_input(
        input_id=input_id,
        modality=TurnInputModality.TEXT,
        text=text,
        final_observations=(observation,),
        actors=(actor(runtime),),
        context_ids=(runtime.state.context_id,),
    )


def shown(runtime: AvatarRuntime, jpeg: bytes) -> EnvObservation:
    perception = runtime.perception
    observation = EnvObservation.video_frame(
        time_range=RuntimeTimeRange.point(perception.clock.now()),
        source=perception.next_source("camera"),
        payload=ImagePayload.create(jpeg_bytes=jpeg),
    )
    perception.publish_observation(observation)
    return observation


def reply(
    runtime: AvatarRuntime,
    turn: TurnSnapshot,
    text: str,
    *tool: ModelFunctionCall | ModelFunctionOutput,
) -> ModelInputMessage:
    message = ModelInputMessage(
        id=f"reply-{turn.input_id}", role=ModelRole.ASSISTANT, parts=(ModelTextPart(text),)
    )
    runtime.output.publish_records(
        model_record_batch(
            batch_id=f"batch-{turn.input_id}",
            source="test.loop",
            scope=OutputScope(runtime.state.context_id, turn.turn_id, f"run-{turn.input_id}"),
            items=(*tool, message),
            identity_basis=runtime.participants.identity_basis(turn),
        )
    )
    return message


async def prepare(context: ContextManager, turn: TurnSnapshot) -> ModelInput:
    prefix = await context.prepare(ContextPrepareRequest(turn=turn, context_id=turn.context_ids[0]))
    # What Loop sends for the first model step.
    return context.build(prefix)


def layout(model_input: ModelInput) -> list[str]:
    return [
        "runtime_context" if getattr(item, "name", None) == RUNTIME_CONTEXT_TOOL_NAME else item.id
        for item in model_input.items
    ]


def kept(context: ContextManager, runtime: AvatarRuntime) -> ModelInput:
    """The canonical History, before a request projects it."""
    return context._history._project(runtime.state.context_id)


def wire(model_input: ModelInput, *, limit: int = 20 * 1024 * 1024) -> list[dict[str, Any]]:
    """The input items the Responses adapter puts on the wire."""
    adapter = ResponsesAdapter(
        ProviderTaskConfig(backend="openai", model="vision-model"),
        ResponsesInputConfig(max_inline_bytes=limit),
        "test",
    )
    return adapter.encode(ModelRequest(input=model_input))["input"]


def images(model_input: ModelInput, *, limit: int = 20 * 1024 * 1024) -> list[str]:
    found = []
    for item in wire(model_input, limit=limit):
        parts = item.get("content", item.get("output"))
        if isinstance(parts, list):
            found.extend(part["image_url"] for part in parts if part["type"] == "input_image")
    return found


def inline(jpeg: bytes) -> str:
    return f"data:image/jpeg;base64,{base64.b64encode(jpeg).decode()}"


async def test_history_keeps_the_image_and_later_requests_mark_its_place(tmp_path: Path) -> None:
    runtime, context = start(tmp_path, vision=VLM)
    try:
        shown(runtime, b"raw-frame")
        first = typed(runtime, "input-1", "What do you see?")
        sent = await prepare(context, first)
        built = wire(sent)[1]["content"]
        assert images(sent) == [inline(b"raw-frame")]
        assert [part["type"] for part in built].count("input_image") == 1
        assert layout(sent) == ["alphaavatar.system", "input-1", *["runtime_context"] * 2]

        answer = reply(runtime, first, "A desk.")
        second = await prepare(context, typed(runtime, "input-2", "Anything else?"))
        # History holds the message the Builder produced, its image included.
        assert kept(context, runtime).items[:2] == (sent.get("input-1"), answer)
        assert images(kept(context, runtime)) == [inline(b"raw-frame")]
        # The request replays it with a marker where the image was, everything else unchanged.
        marked = [MARK if part["type"] == "input_image" else part for part in built]
        assert wire(second)[1] == {"role": "user", "content": marked}
        assert images(second) == []
        assert layout(second) == [
            "alphaavatar.system",
            "input-1",
            "reply-input-1",
            "input-2",
            *["runtime_context"] * 2,
        ]
    finally:
        await context.aclose()
        await runtime.aclose()


async def test_a_retry_resends_the_image_first_fixed_after_perception_annotates_it(
    tmp_path: Path,
) -> None:
    runtime, context = start(tmp_path, vision=VLM)
    try:
        frame = shown(runtime, b"raw-frame")
        first = typed(runtime, "input-1", "What do you see?")
        sent = await prepare(context, first)
        # A perception processor writes its annotated view into the same payload afterwards.
        frame.payload.put(
            PayloadFormat.IMAGE_JPEG_BYTES, b"annotated-frame", view=PayloadView.ANNOTATED
        )
        # The request already built, sent again by a later model step, is unchanged.
        assert images(sent) == [inline(b"raw-frame")]
        # A retry replays the Turn from History; as the current Turn it keeps its image.
        retried = await prepare(context, first)
        assert retried.get("input-1") == sent.get("input-1")
        assert images(retried) == [inline(b"raw-frame")]
        assert layout(retried) == ["alphaavatar.system", "input-1", *["runtime_context"] * 2]

        reply(runtime, first, "A desk.")
        second = await prepare(context, typed(runtime, "input-2", "Anything else?"))
        assert images(kept(context, runtime)) == [inline(b"raw-frame")]
        assert images(second) == []
    finally:
        await context.aclose()
        await runtime.aclose()


async def test_history_tool_images_are_marked_and_keep_their_call_paired(tmp_path: Path) -> None:
    runtime, context = start(tmp_path)
    try:
        first = typed(runtime, "input-1", "What is on my screen?")
        await prepare(context, first)
        call = ModelFunctionCall(
            id="call-item-1", call_id="call-1", name="screenshot", arguments="{}"
        )
        output = ModelFunctionOutput(
            id="call-item-1:result",
            call_id="call-1",
            name="screenshot",
            parts=(
                ModelTextPart("Captured."),
                ModelMediaPart(kind=ModelMediaKind.IMAGE, mime_type="image/jpeg", data=b"screen"),
            ),
            is_error=False,
        )
        reply(runtime, first, "A browser.", call, output)

        second = await prepare(context, typed(runtime, "input-2", "Thanks."))
        assert images(kept(context, runtime)) == [inline(b"screen")]
        assert kept(context, runtime).items[1:3] == (call, output)
        assert wire(second)[2:5] == [
            {"type": "function_call", "call_id": "call-1", "name": "screenshot", "arguments": "{}"},
            {
                "type": "function_call_output",
                "call_id": "call-1",
                "output": "Captured.\n<image_not_replayed />",
            },
            {"role": "assistant", "content": "A browser."},
        ]
        assert layout(second) == [
            "alphaavatar.system",
            "input-1",
            "call-item-1",
            "call-item-1:result",
            "reply-input-1",
            "input-2",
            *["runtime_context"] * 2,
        ]
    finally:
        await context.aclose()
        await runtime.aclose()


async def test_fixed_slices_keep_speech_beside_typing_in_the_request_and_its_history(
    tmp_path: Path,
) -> None:
    fixed = {"perception": {"temporal_alignment": {"mode": "fixed"}}}
    runtime, context = start(tmp_path, runtime=fixed)
    try:
        perception = runtime.perception
        microphone = perception.next_source("microphone")
        began = perception.clock.now().shifted(-3.0)  # The Turn has ended before it commits.

        def said(segment_id: str, start: float, end: float, text: str) -> list[EnvObservation]:
            segment = PerceptionSegmentRef(microphone, segment_id)
            span = RuntimeTimeRange(start=began.shifted(start), end=began.shifted(end))
            return [
                EnvObservation.speech_segment(time_range=span, source=microphone, segment=segment),
                EnvObservation.transcript_segment(
                    time_range=span,
                    source=microphone,
                    segment=segment,
                    payload=TextPayload.create(text=text),
                ),
            ]

        # Speech, typing, then speech that spans two fixed slices with a camera starting inside it.
        inputs = [
            *said("segment-1", 0.0, 0.8, "Look at this"),
            EnvObservation.text_input(
                time_range=RuntimeTimeRange.point(began.shifted(1.0)),
                source=perception.next_source("keyboard"),
                payload=TextPayload.create(text="the red one"),
            ),
            *said("segment-2", 1.2, 2.2, "what is it"),
        ]
        for observation in inputs:
            perception.publish_observation(observation)
        perception.publish_source_state(
            MediaSourceStateEvent(
                source=perception.next_source("camera"),
                modality=MediaModality.VIDEO,
                source_kind=MediaSourceKind.CAMERA,
                state=MediaSourceState.STARTED,
            ),
            at=began.shifted(1.4),
        )
        first = runtime.turn.commit_event_input(
            input_id="input-1",
            modality=TurnInputModality.MULTIMODAL,
            text="Look at this the red one what is it",
            started_at=began,
            committed_at=began.shifted(2.5),
            cutoff_sequence=perception.latest_event_sequence,
            input_observation_ids=[observation.observation_id for observation in inputs],
            actors=(actor(runtime),),
            context_ids=(runtime.state.context_id,),
        )
        sent = await prepare(context, first)
        message = sent.get("input-1")
        text = message.text
        spoken = [
            'segment_id="segment-1" start="+0.00s" end="+0.80s" audio_available="true"',
            "<transcript>Look at this</transcript>",
            'segment_id="segment-2" start="+1.20s" end="+2.20s" audio_available="true"',
            "<transcript>what is it</transcript>",
            '<source_event at="+1.40s"',
            ">the red one</text_input>",
        ]
        positions = [text.find(fragment) for fragment in spoken]
        assert -1 not in positions and positions == sorted(positions)
        assert text.count("<transcript>") == 2 and "<committed_text>" not in text

        answer = reply(runtime, first, "A red mug.")
        second = await prepare(context, typed(runtime, "input-2", "Thanks."))
        assert second.items[1:3] == (message, answer)
        assert layout(second)[3:] == ["input-2", *["runtime_context"] * 2]
    finally:
        await context.aclose()
        await runtime.aclose()


async def test_turn_images_within_the_inline_limit_send_though_history_exceeds_it(
    tmp_path: Path,
) -> None:
    """KD-18: each Turn's image fits Responses ``max_inline_bytes`` but History's together do
    not. Both Turns and a text-only Turn after them still send."""
    runtime, context = start(tmp_path, vision=VLM)
    try:
        shown(runtime, b"1" * 600)
        first = await prepare(context, typed(runtime, "input-1", "What is this?"))
        assert images(first, limit=1000) == [inline(b"1" * 600)]
        shown(runtime, b"2" * 600)
        second = await prepare(context, typed(runtime, "input-2", "And this?"))
        assert images(second, limit=1000) == [inline(b"2" * 600)]
        third = await prepare(context, typed(runtime, "input-3", "Thanks."))
        assert images(third, limit=1000) == []
        assert layout(third)[1:] == ["input-1", "input-2", "input-3", *["runtime_context"] * 2]

        # History still holds both images in full, past the limit together.
        assert images(kept(context, runtime)) == [inline(b"1" * 600), inline(b"2" * 600)]
        with pytest.raises(ModelCapabilityError) as refused:
            images(kept(context, runtime), limit=1000)
        assert refused.value.code == "image_input"
    finally:
        await context.aclose()
        await runtime.aclose()
