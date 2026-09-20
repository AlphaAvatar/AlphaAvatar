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

from typing import TYPE_CHECKING

from livekit.agents.llm import ChatItem, ChatMessage

from alphaavatar.agents.memory.enums import MemoryType
from alphaavatar.agents.memory.schemas import (
    MemoryCheckpointAdvance,
    MemoryScope,
    MemorySourceRef,
)
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.runtime.capability import (
    AvatarCapabilityName,
    avatar_capability,
)

from ...state import MemoryContextState
from ...template import MemoryPluginsTemplate
from ..base import MemoryProcessor
from .config import EnvironmentConfig
from .provider import EnvironmentProvider
from .scheduler import (
    EnvMemoryBatch,
    EnvMemoryScheduler,
)

if TYPE_CHECKING:
    from ...runtime import MemoryRuntime


@avatar_capability(
    name=AvatarCapabilityName.MEMORY_ENVIRONMENT,
    description=(
        "Can form and recall persistent memories from relevant "
        "visual, audio, and environmental observations when "
        "such perception is available."
    ),
)
class EnvironmentProcessor(MemoryProcessor):
    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        memory: MemoryRuntime,
        config: EnvironmentConfig,
    ) -> None:
        super().__init__(
            runtime=runtime,
            memory=memory,
        )

        self._config = config
        self._provider = EnvironmentProvider(config.provider)
        self._scheduler: EnvMemoryScheduler | None = None

    @property
    def name(self) -> str:
        return "environment"

    async def _process_batch(
        self,
        batch: EnvMemoryBatch,
        timeout: float,
    ):
        state = self.memory_runtime.context_state(batch.context_id)

        previous = self.memory_runtime.memory_state.render(
            memory_type=MemoryType.ENV,
            context_id=state.context_id,
        )

        delta = await self._provider.extract(
            memory_input=batch.memory_input,
            previous_env_memory=previous or None,
            conversation_context=batch.conversation_context,
            metadata=self.trace_metadata(
                state=state,
                component="environment",
                operation="environment_delta",
                memory_type=MemoryType.ENV,
                extra={
                    "slice_count": len(batch.memory_input.slices),
                    "media_count": len(batch.memory_input.observations),
                },
            ),
            timeout=timeout,
        )

        source_prefix = state.context.session_id or state.context.episode_id

        items = self.build_memory_items(
            state=state,
            memory_type=MemoryType.ENV,
            patches=delta.env_memory_entries,
            owner_refs=state.owner_refs,
            participant_refs=state.participant_refs,
            source_refs=[
                MemorySourceRef.runtime_event(f"{source_prefix}:{event.sequence}")
                for event in batch.events
            ],
            scope=MemoryScope.context(state.context_id),
            extra_data={
                "trigger": batch.trigger_text,
                "perception_missed_count": batch.missed_count,
            },
        )

        await self.commit_items(
            state=state,
            processor=self.name,
            start=batch.from_sequence,
            end=batch.to_sequence,
            items=items,
        )

        return items

    def on_message(
        self,
        *,
        state: MemoryContextState,
        chat_item: ChatItem,
    ) -> None:
        if (
            isinstance(chat_item, ChatMessage)
            and chat_item.role == "user"
            and self._scheduler is not None
            and self._scheduler.context_id == state.context_id
        ):
            self._scheduler.request("user_turn")

    async def _start(self) -> None:
        if not self.memory_runtime.memory_contexts:
            return

        state = self.memory_runtime.context_state(self.memory_runtime.root_context_id)

        initial_cutoff = self.perception_runtime.capture_cutoff()

        checkpoint = await self.memory_runtime.store.get_checkpoint(
            context_id=state.context_id,
            processor=self.name,
        )

        if checkpoint > initial_cutoff.sequence:
            raise RuntimeError(
                "ENV checkpoint exceeds perception sequence: "
                f"context={state.context_id} "
                f"checkpoint={checkpoint} "
                f"perception={initial_cutoff.sequence}"
            )

        if checkpoint < initial_cutoff.sequence:
            await self.memory_runtime.store.commit(
                [],
                context_id=state.context_id,
                processor=self.name,
                idempotency_key=(
                    f"{state.context_id}:{self.name}:{checkpoint}:{initial_cutoff.sequence}"
                ),
                checkpoint=MemoryCheckpointAdvance(
                    from_sequence=checkpoint,
                    to_sequence=initial_cutoff.sequence,
                ),
            )

        self._scheduler = EnvMemoryScheduler(
            perception_runtime=self.perception_runtime,
            context_state=state,
            initial_cutoff=initial_cutoff,
            process=self._process_batch,
            render_messages=lambda messages: (
                MemoryPluginsTemplate.apply_update_template(
                    messages,
                    state.cache_type,
                )
            ),
            include_audio=self._config.include_audio,
        )

        await self._scheduler.start()

    async def _stop(
        self,
        *,
        finalize: bool,
    ) -> None:
        if self._scheduler is None:
            return

        try:
            await self._scheduler.stop(finalize=finalize)
        finally:
            self._scheduler = None
