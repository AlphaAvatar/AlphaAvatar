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

import asyncio
import logging
import pathlib
from collections.abc import Sequence
from datetime import UTC, datetime

from alphaavatar.agents.avatar.provider.records import MODEL_RECORD_SCHEMA
from alphaavatar.agents.avatar.provider.schemas.model_input import ModelInputItem
from alphaavatar.agents.memory import MemoryBase
from alphaavatar.agents.memory.enums import (
    MemoryCacheType,
    MemoryOwnerKind,
    MemoryScopeKind,
    MemoryType,
)
from alphaavatar.agents.memory.schemas import (
    MemoryContextRef,
    MemoryItem,
    MemoryOwnerRef,
    MemoryParticipantRef,
    MemoryScope,
)
from alphaavatar.agents.runtime import AvatarRuntime
from alphaavatar.agents.runtime.capability import AvatarCapabilityRegistry
from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.output import OutputJournalGap
from alphaavatar.core.output.schemas import OutputRecordBatch
from alphaavatar.core.session import Participant
from alphaavatar.core.turn.enums import TurnInputModality
from alphaavatar.core.turn.schemas import TurnSnapshot

from .processors.base import MemoryProcessor
from .schemas import MemoryIdentitySnapshot
from .state import MemoryContextState, MemoryState
from .storage import MemoryStore

logger = logging.getLogger(__name__)


class MemoryRuntime(MemoryBase):
    TURN_CONSUMER_ID = "memory.runtime.turn"
    RECORD_CONSUMER_ID = "memory.runtime.output_records"
    SESSION_CONSUMER_ID = "memory.runtime.session"

    def __init__(
        self,
        *,
        runtime: AvatarRuntime,
        avatar_id: str,
        store: MemoryStore,
        maximum_memory_num: int = 24,
    ) -> None:
        self._runtime = runtime
        self._avatar_id = avatar_id
        self._store = store
        self._memory_contexts: dict[str, MemoryContextState] = {}
        self._memory_state = MemoryState(maximum_memory_num=maximum_memory_num)
        self._root_context_id: str | None = None
        self._processors: tuple[MemoryProcessor, ...] = ()
        self._entered_processors: list[MemoryProcessor] = []
        self._processors_bound = False
        self._started = False
        self._capability_registry = AvatarCapabilityRegistry()
        self._turn_task: asyncio.Task[None] | None = None
        self._session_task: asyncio.Task[None] | None = None
        self._record_task: asyncio.Task[None] | None = None
        self._record_error: Exception | None = None
        self._record_registered = False
        self._record_stopping = False
        self._close_task: asyncio.Task[None] | None = None
        self._start_task: asyncio.Task[None] | None = None
        self._store_open = False

    @property
    def avatar_id(self) -> str:
        return self._avatar_id

    @property
    def store(self) -> MemoryStore:
        return self._store

    @property
    def capability_registry(self) -> AvatarCapabilityRegistry:
        return self._capability_registry

    @property
    def root_context_id(self) -> str:
        if self._root_context_id is None:
            raise RuntimeError("Memory root context is not initialized")
        return self._root_context_id

    @property
    def memory_contexts(self) -> dict[str, MemoryContextState]:
        return self._memory_contexts

    @property
    def memory_state(self) -> MemoryState:
        return self._memory_state

    @property
    def memory_content(self) -> str:
        self.sync_session()
        return self._render_content()

    @staticmethod
    def _observe(task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()

    def _render_content(
        self,
        identity: MemoryIdentitySnapshot | None = None,
        context: MemoryContextRef | None = None,
    ) -> str:
        kinds = (MemoryType.Avatar, MemoryType.CONVERSATION, MemoryType.TOOLS, MemoryType.ENV)
        return "\n".join(
            item.render_line()
            for kind in kinds
            for item in self.visible_items(
                self._memory_state.get(memory_type=kind), identity=identity, context=context
            )
        )

    def content_for(self, snapshot: TurnSnapshot) -> str:
        if self._runtime.turn.get(snapshot.input_id) is not snapshot:
            raise ValueError("Memory context requires a Turn owned by this runtime")
        self.sync_session()
        context_id = self.resolve_context_id(snapshot.context_ids)
        if context_id is None:
            return ""
        state = self.context_state(context_id)
        return self._render_content(state.capture_identity([snapshot]), state.context)

    def visible_items(
        self,
        items: Sequence[MemoryItem],
        *,
        identity: MemoryIdentitySnapshot | None = None,
        context: MemoryContextRef | None = None,
    ) -> list[MemoryItem]:
        users = {
            participant.user_id
            for participant in (
                () if identity is None or identity.unattributed else identity.participants
            )
            if participant.user_id is not None
            and self._runtime.participants.accepts_identity(participant)
        }
        scopes = set(MemoryScope.applicable_keys(context)) if context is not None else None
        return [
            item
            for item in items
            if any(
                (ref.kind is MemoryOwnerKind.AVATAR and ref.id == self._avatar_id)
                or (ref.kind is MemoryOwnerKind.USER and ref.id in users)
                for ref in item.owner_refs
            )
            and (
                item.scope.key in scopes
                if scopes is not None
                else item.scope.kind is MemoryScopeKind.OWNER
                or (
                    item.scope.kind is MemoryScopeKind.CONTEXT
                    and item.context.context_id in self._memory_contexts
                )
            )
        ]

    def identity_is_current(self, identity: MemoryIdentitySnapshot) -> bool:
        return all(
            self._runtime.participants.accepts_identity(participant)
            for participant in identity.participants
        ) and all(
            actor.participant_id is None
            or (
                (current := self._runtime.participants.get(actor.participant_id)) is not None
                and current.user_id == actor.user_id
                and current.identity_sequence == actor.identity_sequence
            )
            for actor in identity.actors
        )

    def bind_processors(self, processors: Sequence[MemoryProcessor]) -> None:
        if self._processors_bound:
            raise RuntimeError("Memory processors have already been bound")
        if self._start_task is not None or self._close_task is not None:
            raise RuntimeError("Memory processors cannot be bound after runtime start or stop")

        names = [processor.name for processor in processors]
        if len(names) != len(set(names)):
            raise ValueError(f"Memory processor names must be unique: {names}")

        registry = AvatarCapabilityRegistry(*processors)
        self._processors = tuple(processors)
        self._capability_registry = registry
        self._processors_bound = True

    def context_state(self, context_id: str) -> MemoryContextState:
        state = self._memory_contexts.get(context_id)
        if state is None:
            raise ValueError(f"Memory context not found: {context_id}")
        return state

    def open_context(
        self,
        *,
        context: MemoryContextRef,
        provider_dir: pathlib.Path,
        owner_refs: list[MemoryOwnerRef],
        participant_refs: list[MemoryParticipantRef] | None = None,
        cache_type: MemoryCacheType = MemoryCacheType.SESSION_INTERACTION,
        participants: tuple[Participant, ...] = (),
    ) -> MemoryContextState:
        if context.context_id in self._memory_contexts:
            raise ValueError(f"Memory context already exists: {context.context_id}")

        state = MemoryContextState(
            context=context,
            provider_dir=provider_dir,
            owner_refs=owner_refs,
            participant_refs=participant_refs,
            cache_type=cache_type,
            participants=participants,
        )
        self._memory_contexts[context.context_id] = state
        state.sync_identity(self._runtime.session.snapshot())
        return state

    def close_context(self, context_id: str) -> MemoryContextState:
        state = self.context_state(context_id)
        if any(
            item.context.parent_context_id == context_id for item in self._memory_contexts.values()
        ):
            raise RuntimeError(f"Memory context has open children: {context_id}")
        del self._memory_contexts[context_id]
        if self._root_context_id == context_id:
            self._root_context_id = None
        return state

    def sync_session(self) -> None:
        session = self._runtime.session
        batch = session.events.read_pending(consumer_id=self.SESSION_CONSUMER_ID)
        if not batch.items and not batch.has_gap:
            return

        snapshot = session.snapshot()
        # Identity events update views only. They never rewrite owners of durable records.
        for state in self._memory_contexts.values():
            state.sync_identity(snapshot, include_new=state.context_id == self._root_context_id)

        session.events.commit(consumer_id=self.SESSION_CONSUMER_ID, cursor_seq=snapshot.sequence)

    def _accept_messages(
        self, *, context_id: str, items: Sequence[ModelInputItem], turn_id: str | None = None
    ) -> None:
        if not self._record_registered:
            raise RuntimeError("Memory record consumer is not registered")
        state = self.context_state(context_id)
        self.sync_session()
        state.add_messages(items, turn_id=turn_id)

    def apply_items(self, items: list[MemoryItem]) -> None:
        superseded = {memory_id for item in items for memory_id in item.supersedes_memory_ids}
        if superseded:
            self._memory_state.discard(superseded)

        # Retain one shared cache; each Turn projects only its own accepted participants.
        current = [item for item in items if item.memory_id not in superseded]
        for memory_type in MemoryType:
            bucket = [item for item in current if item.memory_type is memory_type]
            if bucket:
                self._memory_state.add(memory_type, bucket)

    """Runtime Loop"""

    def resolve_context_id(self, context_ids: Sequence[str]) -> str | None:
        if context_ids:
            return next((key for key in context_ids if key in self._memory_contexts), None)
        return self._root_context_id

    def _record_turn(self, snapshot: TurnSnapshot) -> None:
        if snapshot.modality == TurnInputModality.SYSTEM:
            return
        context_id = self.resolve_context_id(snapshot.context_ids)
        if context_id is None:
            logger.warning(
                "Memory has no context for turn turn_id=%s context_ids=%s",
                snapshot.turn_id,
                snapshot.context_ids,
            )
            return
        self.context_state(context_id).add_turn(snapshot)
        self.sync_session()

    def _drain_turns(self) -> None:
        stream = self._runtime.turn.events
        while True:
            batch = stream.read_pending(consumer_id=self.TURN_CONSUMER_ID, limit=32)
            for event in batch.items:
                self._record_turn(event.snapshot)
            if batch.cursor_seq > batch.committed_cursor_seq:
                stream.commit(consumer_id=self.TURN_CONSUMER_ID, cursor_seq=batch.cursor_seq)
            if not batch.items or batch.remaining_count == 0:
                return

    def _read_records(self) -> int:
        journal = self._runtime.output.records
        batch = journal.read_pending(consumer_id=self.RECORD_CONSUMER_ID, limit=32)
        if batch.has_gap:
            raise OutputJournalGap("Memory missed canonical output records")
        # Turns own user input. Ensure already committed users precede dependent model records.
        if self._turn_task is not None:
            self._drain_turns()

        for event in batch.items:
            record = event.payload
            if not isinstance(record, OutputRecordBatch):
                raise TypeError("Output records require a batch envelope")
            if event.session_id != self._runtime.session.session_id:
                raise ValueError("Output records belong to another session")

            if record.schema == MODEL_RECORD_SCHEMA:
                self._accept_messages(
                    context_id=record.scope.context_id,
                    items=record.items,
                    turn_id=record.scope.turn_id,
                )
            elif record.schema.startswith("alphaavatar.model.records."):
                raise ValueError(f"Unsupported Memory record version: {record.schema}")

            # Unrelated record families have their own consumers; never interpret their payloads.
            journal.commit(consumer_id=self.RECORD_CONSUMER_ID, cursor_seq=event.sequence)

        return batch.latest_seq - batch.cursor_seq

    async def _consume_turns(self) -> None:
        stream = self._runtime.turn.events
        while True:
            try:
                await stream.wait_for_pending(consumer_id=self.TURN_CONSUMER_ID)
                batch = stream.read_pending(consumer_id=self.TURN_CONSUMER_ID, limit=16)
                for event in batch.items:
                    self._record_turn(event.snapshot)
                stream.commit(consumer_id=self.TURN_CONSUMER_ID, cursor_seq=batch.cursor_seq)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Memory turn consumer failed")
                await asyncio.sleep(0.05)

    async def _consume_records(self) -> None:
        journal = self._runtime.output.records
        try:
            while await journal.wait_for_pending(consumer_id=self.RECORD_CONSUMER_ID):
                self._read_records()
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            if not self._record_stopping:
                error = RuntimeError("Memory record consumer was cancelled unexpectedly")
                self._record_error = error
                journal.fail(self.RECORD_CONSUMER_ID, error)

            raise
        except Exception as exc:
            self._record_error = exc
            journal.fail(self.RECORD_CONSUMER_ID, exc)
            logger.exception("Memory canonical record consumer failed")

    async def _consume_session(self) -> None:
        stream = self._runtime.session.events
        while await stream.wait_for_pending(consumer_id=self.SESSION_CONSUMER_ID):
            self.sync_session()

    """Runtime operations"""

    def _open_root_context(self) -> None:
        if self._root_context_id is not None:
            return

        session_path = self._runtime.session_path
        state_runtime = self._runtime.state

        context = MemoryContextRef(
            episode_id=state_runtime.episode_id,
            context_id=state_runtime.context_id,
            session_id=self._runtime.session.session_id,
            created_at=datetime.fromtimestamp(self._runtime.session.created_at.unix_seconds, UTC),
        )
        self.open_context(
            context=context,
            provider_dir=session_path.provider_dir,
            owner_refs=[MemoryOwnerRef.avatar(self._avatar_id)],
            participant_refs=[MemoryParticipantRef.avatar(self._avatar_id)],
            participants=tuple(self._runtime.session.participants.values()),
        )
        self._root_context_id = context.context_id
        self.sync_session()

    def _start_record_consumer(self) -> None:
        journal = self._runtime.output.records
        journal.register(self.RECORD_CONSUMER_ID, required=True)
        self._record_registered = True
        self._record_stopping = False
        self._record_task = asyncio.create_task(
            self._consume_records(), name="memory_output_records"
        )

    async def _stop_record_consumer(self, *, drain: bool) -> None:
        self._record_stopping = True
        task, self._record_task = self._record_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if not self._record_registered:
            return
        try:
            if self._record_error is not None:
                raise RuntimeError("Memory output record ingestion failed") from self._record_error
            if drain:
                while self._read_records():
                    await asyncio.sleep(0)
        finally:
            self._runtime.output.records.unregister(self.RECORD_CONSUMER_ID)
            self._record_registered = False

    async def _stop_turn_consumer(self, *, drain: bool) -> None:
        self._runtime.turn.unregister_context_consumer(self.TURN_CONSUMER_ID)
        if self._turn_task is not None:
            self._turn_task.cancel()
            await asyncio.gather(self._turn_task, return_exceptions=True)
            self._turn_task = None
        try:
            if drain:
                self._drain_turns()
        finally:
            self._runtime.turn.events.clear_consumer(self.TURN_CONSUMER_ID)

    async def _start(self) -> None:
        # The close path owns even a partially initialized store.
        self._store_open = True
        await self._store.start()
        self._open_root_context()
        self._session_task = asyncio.create_task(
            self._consume_session(), name=self.SESSION_CONSUMER_ID
        )
        self._session_task.add_done_callback(self._observe)
        self._runtime.turn.register_context_consumer(self.TURN_CONSUMER_ID)
        self._turn_task = asyncio.create_task(self._consume_turns(), name="memory_turn_consumer")
        self._start_record_consumer()
        for processor in self._processors:
            # Own partial initialization before the processor can suspend or fail.
            self._entered_processors.append(processor)
            await processor.start()
            if self._record_error is not None:
                raise RuntimeError("Memory output ingestion failed during startup")

        task = asyncio.current_task()
        if self._close_task is not None or (task is not None and task.cancelling()):
            raise asyncio.CancelledError
        self._started = True

    async def _close(self) -> None:
        start = self._start_task
        if start is not None:
            if not start.done():
                start.cancel()
            await asyncio.gather(start, return_exceptions=True)
        finalize = self._started
        self._started = False
        errors: list[Exception] = []

        async def close_step(operation) -> None:
            try:
                await operation
            except asyncio.CancelledError as exc:
                error = RuntimeError("Memory cleanup operation cancelled itself")
                error.__cause__ = exc
                errors.append(error)
            except Exception as exc:
                errors.append(exc)

        # Drain records before final extraction. One failure must not skip later cleanup.
        await close_step(self._stop_turn_consumer(drain=finalize))
        await close_step(self._stop_record_consumer(drain=finalize))
        for processor in reversed(self._entered_processors):
            await close_step(processor.stop(finalize=finalize))

        self._entered_processors.clear()
        if self._session_task is not None:
            self._session_task.cancel()
            await asyncio.gather(self._session_task, return_exceptions=True)
            self._session_task = None
        self._runtime.session.events.clear_consumer(self.SESSION_CONSUMER_ID)
        if self._store_open:
            self._store_open = False
            await close_step(self._store.stop())
        if errors:
            raise ExceptionGroup("Memory shutdown failed", errors)

    async def on_start(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("Memory runtime is closing or closed")
        if not self._processors_bound:
            raise RuntimeError("Memory processors have not been bound")
        if self._start_task is None:
            self._start_task = asyncio.create_task(self._start(), name="memory_runtime_start")
            self._start_task.add_done_callback(self._observe)
        try:
            await asyncio.shield(self._start_task)
            if self._close_task is not None:
                raise RuntimeError("Memory closed during startup")
        except BaseException as original:
            try:
                await self.on_stop()
            except BaseException as cleanup_error:
                raise original from cleanup_error
            raise

    async def on_stop(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="memory_runtime_close")
            self._close_task.add_done_callback(self._observe)
        await wait_for_cleanup(self._close_task)
