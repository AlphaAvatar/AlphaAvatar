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
import inspect
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from alphaavatar.agents.log import logger
from alphaavatar.agents.router.enums import TurnTakingAction, TurnTakingMode
from alphaavatar.agents.router.schemas import TurnTakingDecision
from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.env.enums import AnnotationKind, ObservationKind
from alphaavatar.core.env.schemas import (
    PerceptionEntityRef,
    PerceptionSegmentRef,
    PerceptionSourceRef,
)
from alphaavatar.core.lifecycle import LifecycleComponent, LifecycleGroup, LifecyclePhase
from alphaavatar.core.log.events import log_event
from alphaavatar.core.media import TextPayload
from alphaavatar.core.output.enums import ExecutionSignalKind
from alphaavatar.core.output.schemas import OutputExecutionSignal, OutputScope
from alphaavatar.core.turn.enums import TurnInputModality
from alphaavatar.core.turn.schemas import TurnEntityRef

from .loop.schemas import LoopRequest

if TYPE_CHECKING:
    from alphaavatar.agents.configs import AvatarConfig
    from alphaavatar.agents.router.schemas import InteractionEntityRef
    from alphaavatar.agents.runtime import AvatarRuntime
    from alphaavatar.core.perception.schemas import PerceptionEvent
    from alphaavatar.core.session import SessionRuntime
    from alphaavatar.core.turn.schemas import TurnSnapshot

    from .loop import LoopHandle
    from .loop.base import ToolAuthorizer


@dataclass(slots=True)
class _Foreground:
    turn_id: str
    context_id: str
    cutoff_sequence: int
    handle: LoopHandle | None = None
    interrupted: bool = False


class TurnAdmissionRejected(RuntimeError):
    """No Turn or execution was accepted before the Engine closed."""


class AvatarEngine(LifecycleComponent):
    """Own turn admission and native execution, not transport, prompts or record persistence."""

    CONSUMER_ID = "avatar.engine.turns"

    def __init__(
        self,
        *,
        avatar_config: AvatarConfig,
        runtime: AvatarRuntime,
        authorize: ToolAuthorizer | None = None,
    ) -> None:
        self._avatar_config = avatar_config
        self._runtime = runtime

        foundation = runtime.foundation
        if foundation is None or not foundation.loop.ready:
            raise RuntimeError("AvatarEngine requires an initialized Foundation Loop")
        if authorize is not None and not callable(authorize):
            raise TypeError("Tool authorizer must be callable")

        self._config = avatar_config.runtime.engine
        self._loop, self._authorize = foundation.loop, authorize

        # Step 1: initialize perception plugins and tools plugins.
        self._status = avatar_config.status.get_plugin(runtime=runtime)
        self._router = avatar_config.router.get_plugin(runtime=runtime)
        self._memory = avatar_config.memory.get_plugin(
            runtime=runtime, avatar_id=avatar_config.avatar.id
        )
        self._persona = avatar_config.persona.get_plugin(runtime)
        self._tool_plugins = avatar_config.tools.get_tools(runtime)

        # Step 2: initialize runtime capability.
        runtime.capability_registry.collect(self._memory, self._persona, *self._tool_plugins)

        # Step 3: bind memory and persona to runtime context.
        self._context_manager = foundation.context
        self._context_manager.bind_sources(memory=self._memory, persona=self._persona)

        # Step 4: manage Agent-owned consumers before enabling the Router.
        self._plugins = LifecycleGroup(
            phases=(
                LifecyclePhase.create("avatar-status", (self._status,)),
                LifecyclePhase.create("avatar-tools", self._tool_plugins),
                LifecyclePhase.create("avatar-memory", (self._memory,)),
                LifecyclePhase.create("avatar-persona", (self._persona,)),
            )
        )
        self._routers = LifecycleGroup(
            phases=(LifecyclePhase.create("avatar-router", (self._router,)),)
        )
        self._admission_lock = asyncio.Lock()
        self._admissions: set[asyncio.Task[object]] = set()
        self._watchers: set[asyncio.Task[None]] = set()

        # Session-bounded tombstones are not evicted while an input can be replayed.
        self._candidates: dict[str, set[TurnTakingAction]] = {}
        self._foreground: _Foreground | None = None
        self._intake: asyncio.Task[None] | None = None
        self._start_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._intake_stopping = self._ready = False
        self._failure: Exception | None = None
        self._failed = asyncio.Event()

    @property
    def session_runtime(self) -> SessionRuntime:
        return self._runtime.session

    @property
    def ready(self) -> bool:
        return self._ready and self._close_task is None and self._failure is None

    @staticmethod
    def _failure_from(error: BaseException, label: str) -> Exception:
        if isinstance(error, Exception):
            return error
        if isinstance(error, asyncio.CancelledError):
            failure = RuntimeError(f"{label} cancelled without owner shutdown")
            failure.__cause__ = error
            return failure
        raise error

    @staticmethod
    def _text(observations: tuple[EnvObservation, ...]) -> str | None:
        parts = [
            observation.payload.text
            for observation in observations
            if observation.kind in (ObservationKind.TEXT_INPUT, ObservationKind.TRANSCRIPT_SEGMENT)
            and isinstance(observation.payload, TextPayload)
            and observation.payload.text.strip()
        ]
        return " ".join(parts) or None

    @staticmethod
    def _observe_close(task: asyncio.Task[None]) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("AvatarEngine cleanup failed", exc_info=error)

    @classmethod
    async def _step(
        cls, operation: Callable[[], object], errors: list[Exception], label: str
    ) -> None:
        try:
            result = operation()
            if inspect.isawaitable(result):
                await result
        except BaseException as error:
            errors.append(cls._failure_from(error, label))

    """Runtime Helper"""

    def _ensure_open(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("AvatarEngine is closing or closed")
        if self._failure is not None:
            raise RuntimeError("AvatarEngine has failed") from self._failure

    def _fail(self, error: BaseException, label: str) -> None:
        failure = self._failure_from(error, label)
        if self._failure is None:
            self._failure = failure
            self._failed.set()
            logger.error("AvatarEngine failed: %s", label, exc_info=failure)
        self._ensure_close()

    def _observe(self, task: asyncio.Task) -> None:
        if task is self._intake and self._intake_stopping and task.cancelled():
            return
        try:
            task.result()
        except TurnAdmissionRejected:
            if self._close_task is None:
                self._fail(RuntimeError("Unexpected admission refusal"), task.get_name())
        except BaseException as error:
            self._fail(error, task.get_name())
        else:
            if task is self._intake and not self._intake_stopping:
                self._fail(RuntimeError("Turn consumer exited unexpectedly"), task.get_name())

    def _candidate(self, input_id: str) -> set[TurnTakingAction]:
        if not isinstance(input_id, str) or not input_id.strip() or len(input_id) > 512:
            raise ValueError("Turn input identity must contain 1..512 characters")

        flags = self._candidates.get(input_id)
        if flags is None:
            if len(self._candidates) >= self._config.max_turn_candidates:
                raise RuntimeError("Session turn admission capacity exhausted")

            flags = self._candidates[input_id] = set()
        return flags

    def _schedule_admission(self, operation: Coroutine[Any, Any, object]) -> asyncio.Task[object]:
        try:
            self._ensure_open()
            if len(self._admissions) >= self._config.max_pending_admissions:
                raise RuntimeError("Turn admission queue is full")
        except BaseException:
            operation.close()
            raise

        task = asyncio.create_task(operation, name="avatar_turn_admission")
        self._admissions.add(task)
        task.add_done_callback(self._admissions.discard)
        task.add_done_callback(self._observe)
        return task

    def _cancel_foreground(self, foreground: _Foreground | None, reason: str) -> None:
        if foreground is None:
            return

        foreground.interrupted = True
        if foreground.handle is not None:
            run_id = foreground.handle.identity.run_id
            # Successful generation does not revoke playout. An explicit interruption does.
            self._runtime.output.revoke_run(run_id)
            self._loop.interrupt(run_id=run_id, reason=reason)

    def _participant_entity(
        self,
        device_id: str | None,
        *,
        kind: str = "person",
        entity: PerceptionEntityRef | None = None,
        source: PerceptionSourceRef | None = None,
        segment: PerceptionSegmentRef | None = None,
        endpoint: bool = False,
    ) -> TurnEntityRef:
        participant = self._runtime.participants.resolve(
            device_id, source=source, entity=entity, segment=segment, endpoint=endpoint
        )
        if entity is None and segment is not None:
            entity = self._runtime.participants.entity_for_segment(segment)

        # Perception labels are evidence; only the Session owns accepted user bindings.
        return TurnEntityRef(
            kind=kind,
            participant_id=participant.participant_id if participant is not None else None,
            identity_sequence=participant.identity_sequence if participant is not None else None,
            user_id=participant.user_id if participant is not None else None,
            device_id=device_id,
            entity=entity,
        )

    def _entity(
        self,
        ref: InteractionEntityRef,
        *,
        source: PerceptionSourceRef | None = None,
        segment: PerceptionSegmentRef | None = None,
    ) -> TurnEntityRef:
        return self._participant_entity(
            ref.device_id,
            kind=ref.kind.value,
            entity=ref.entity,
            source=ref.source if ref.source is not None else source,
            segment=segment,
        )

    def _decision_actor(
        self, ref: InteractionEntityRef, observations: tuple[EnvObservation, ...]
    ) -> TurnEntityRef:
        sources = {
            value.segment.source if value.segment is not None else value.source
            for value in observations
        }
        actor = self._entity(ref, source=next(iter(sources)) if len(sources) == 1 else None)
        segments = {value.segment for value in observations if value.segment is not None}
        if not segments:
            return actor

        participants = [self._runtime.participants.resolve(segment=segment) for segment in segments]
        first = participants[0]
        if (
            first is None
            or any(
                value is None or value.participant_id != first.participant_id
                for value in participants
            )
            or (actor.participant_id is not None and actor.participant_id != first.participant_id)
            or (ref.entity is not None and actor.participant_id is None)
        ):
            # A merged Turn cannot discard an unknown/conflicting segment's ownership constraint.
            return replace(actor, participant_id=None, user_id=None, identity_sequence=None)

        entity = actor.entity
        if entity is None and len(segments) == 1:
            entity = self._runtime.participants.entity_for_segment(next(iter(segments)))

        return replace(
            actor,
            participant_id=first.participant_id,
            user_id=first.user_id,
            identity_sequence=first.identity_sequence,
            entity=entity,
        )

    async def _own_admission(self, operation: Coroutine[Any, Any, object]) -> object:
        return await wait_for_cleanup(self._schedule_admission(operation))

    async def _watch(self, handle: LoopHandle) -> None:
        result = await handle.wait()
        if result.error_type is not None:
            logger.warning(
                "Native run finished run_id=%s state=%s reason=%s error=%s",
                handle.identity.run_id,
                result.state.value,
                result.reason,
                result.error_type,
            )
        # Loop owns records and FINISHED facts. Never reconstruct either from this result.

    """Turn Actio - Interrupt"""

    async def _interrupt_foreground(self, foreground: _Foreground | None, reason: str) -> None:
        self._cancel_foreground(foreground, reason)
        if foreground is not None:
            await self._runtime.output.interrupt(turn_id=foreground.turn_id, reason=reason)

    """Turn Action - Commit or Direct Input"""

    async def _submit(self, snapshot: TurnSnapshot) -> None:
        # Observe only committed input. No Run exists yet, and no prompt/history is logged.
        log_event(
            logger,
            "input.committed",
            text=snapshot.text,
            session_id=self._runtime.session.session_id,
            context_id=self._runtime.state.context_id,
            turn_id=snapshot.turn_id,
            input_id=snapshot.input_id,
            modality=snapshot.modality.value,
        )
        model_input = self._context_manager.accept_turn(snapshot)
        context_id = self._runtime.state.context_id
        previous, foreground = (
            self._foreground,
            _Foreground(snapshot.turn_id, context_id, snapshot.cutoff.sequence),
        )
        self._foreground = foreground
        self._cancel_foreground(previous, "superseded")
        if previous is not None:
            await self._runtime.output.interrupt(turn_id=previous.turn_id, reason="superseded")

        await self._runtime.output.start_turn(turn_id=snapshot.turn_id)
        if foreground.interrupted or self._close_task is not None:
            return

        if self._runtime.state.context_id != context_id:
            raise RuntimeError("Context changed during Turn admission")

        request = LoopRequest(
            input_id=snapshot.input_id,
            turn_id=snapshot.turn_id,
            context_id=context_id,
            input=model_input,
            allowed_capabilities=tuple(
                capability.id
                for capability in self._runtime.capability_registry.capabilities
                if capability.callable
            ),
            limits=self._config.loop_limits,
            depth=self._config.depth,
        )
        handle = await self._loop.submit(request, authorize=self._authorize)
        foreground.handle = handle

        # A different Loop implementation may suspend while accepting the request.
        if foreground.interrupted or self._close_task is not None:
            self._cancel_foreground(foreground, "interrupted_during_admission")
            await self._runtime.output.interrupt(
                turn_id=foreground.turn_id, reason="interrupted_during_admission"
            )

        task = asyncio.create_task(self._watch(handle), name=f"avatar_run:{handle.identity.run_id}")
        self._watchers.add(task)
        task.add_done_callback(self._watchers.discard)
        task.add_done_callback(self._observe)

    def _trace_admission(
        self,
        event: PerceptionEvent,
        decision: TurnTakingDecision,
        *,
        outcome: str,
        reason: str,
        evidence_count: int = 0,
        missing_count: int = 0,
    ) -> None:
        trace = self._runtime.perception.input_trace
        trace.record(
            "turn.admission",
            candidate_id=decision.turn_candidate_id,
            candidate_revision=decision.candidate_revision,
            decision_id=event.annotation.annotation_id,
            event_id=event.event_id,
            sequence=event.sequence,
            outcome=outcome,
            reason=reason,
            evidence_count=evidence_count,
            missing_count=missing_count,
        )
        if outcome == "rejected":
            trace.freeze(reason=reason)

    async def _admit_decision(self, event: PerceptionEvent, decision: TurnTakingDecision) -> None:
        async with self._admission_lock:
            if self._close_task is not None:
                raise TurnAdmissionRejected("Engine closed before Turn admission")

            flags = self._candidate(decision.turn_candidate_id)
            if flags.intersection((TurnTakingAction.COMMIT, TurnTakingAction.CANCEL)):
                self._trace_admission(
                    event, decision, outcome="ignored", reason="candidate_terminal"
                )
                return

            latest = self._runtime.turn.latest
            if latest is not None and event.sequence <= latest.cutoff.sequence:
                flags.add(TurnTakingAction.COMMIT)
                logger.info(
                    "Skipped superseded turn decision input_id=%s", decision.turn_candidate_id
                )
                self._trace_admission(event, decision, outcome="ignored", reason="superseded")
                return

            observations = tuple(
                self._runtime.perception.timeline.get_observation(observation_id=value)
                for value in dict.fromkeys(decision.input_observation_ids)
            )
            if not observations or any(value is None for value in observations):
                # This is a proposed Turn, not an admitted one. Reject the entire candidate;
                # never substitute newer evidence or kill a healthy session after retention loss.
                flags.add(TurnTakingAction.CANCEL)
                logger.warning(
                    "Turn admission rejected input_id=%s reason=evidence_unavailable "
                    "decision_sequence=%s evidence_count=%s missing_count=%s",
                    decision.turn_candidate_id,
                    event.sequence,
                    len(observations),
                    sum(value is None for value in observations),
                )
                self._trace_admission(
                    event,
                    decision,
                    outcome="rejected",
                    reason="evidence_unavailable",
                    evidence_count=len(observations),
                    missing_count=sum(value is None for value in observations),
                )
                return

            text = self._text(observations)
            if text is None and not any(
                value.kind
                in (
                    ObservationKind.IMAGE_INPUT,
                    ObservationKind.VIDEO_FRAME,
                    ObservationKind.SCREEN_FRAME,
                )
                for value in observations
            ):
                flags.add(TurnTakingAction.CANCEL)
                logger.info(
                    "Turn admission rejected input_id=%s reason=no_usable_input",
                    decision.turn_candidate_id,
                )
                self._trace_admission(
                    event,
                    decision,
                    outcome="rejected",
                    reason="no_usable_input",
                    evidence_count=len(observations),
                )
                return

            mode = decision.turn_mode
            modality = (
                TurnInputModality.AUDIO
                if mode == TurnTakingMode.AUDIO_ONLY
                else TurnInputModality.IMAGE
                if mode == TurnTakingMode.VISUAL_ONLY
                else TurnInputModality.MULTIMODAL
            )
            flags.add(TurnTakingAction.COMMIT)
            snapshot = self._runtime.turn.commit_event_input(
                input_id=decision.turn_candidate_id,
                modality=modality,
                text=text,
                started_at=min(
                    (value.time_range.start for value in observations),
                    key=lambda value: value.monotonic_ns,
                ),
                committed_at=event.time_range.end,
                cutoff_sequence=event.sequence,
                input_observation_ids=decision.input_observation_ids,
                actors=(self._decision_actor(decision.actor, observations),)
                if decision.actor is not None
                else (),
                addressees=tuple(self._entity(ref) for ref in decision.addressees),
                context_ids=(self._runtime.state.context_id,),
                metadata={
                    "candidate_revision": decision.candidate_revision,
                    "decision_event_id": event.event_id,
                    "decision_event_sequence": event.sequence,
                    "decision_annotation_id": event.annotation.annotation_id,
                    "reason": decision.reason,
                },
            )
            self._trace_admission(
                event,
                decision,
                outcome="accepted",
                reason="committed",
                evidence_count=len(observations),
            )
            await self._submit(snapshot)

    async def _admit_input(self, observation: EnvObservation) -> None:
        async with self._admission_lock:
            if self._close_task is not None:
                raise TurnAdmissionRejected("Engine closed before Turn admission")

            flags = self._candidate(observation.observation_id)
            if TurnTakingAction.COMMIT in flags:
                return

            flags.add(TurnTakingAction.COMMIT)
            snapshot = self._runtime.turn.commit_input(
                input_id=observation.observation_id,
                modality=TurnInputModality.TEXT
                if observation.kind == ObservationKind.TEXT_INPUT
                else TurnInputModality.IMAGE,
                text=self._text((observation,)),
                final_observations=(observation,),
                actors=(
                    self._participant_entity(
                        observation.device_id,
                        entity=observation.entity,
                        source=observation.source,
                        endpoint=True,
                    ),
                ),
                context_ids=(self._runtime.state.context_id,),
                metadata={"source": "avatar.engine.direct"},
            )
            await self._submit(snapshot)

    async def submit_input(self, observation: EnvObservation) -> None:
        """Accept a direct input; Core publishes it and captures the Turn cutoff atomically."""
        self._ensure_open()
        if not self.ready:
            raise RuntimeError("AvatarEngine is not ready for direct inputs")

        if type(observation) is not EnvObservation or observation.kind not in (
            ObservationKind.TEXT_INPUT,
            ObservationKind.IMAGE_INPUT,
        ):
            raise TypeError("Direct input requires TEXT_INPUT or IMAGE_INPUT")

        if observation.kind == ObservationKind.TEXT_INPUT:
            if (
                not isinstance(observation.payload, TextPayload)
                or not observation.payload.text.strip()
            ):
                raise ValueError("Direct text input must contain text")
            if len(observation.payload.text.encode("utf-8")) > self._config.max_input_bytes:
                raise ValueError("Direct text input exceeds its byte limit")
            payload = TextPayload.create(text=observation.payload.text)
        else:
            if not observation.has_payload:
                raise ValueError("Direct image input requires media evidence")
            payload = observation.payload

        # Copy text and the outer metadata mapping; media keeps Core evidence ownership.
        observation = replace(
            observation,
            payload=payload,
            metadata=dict(observation.metadata),
            annotations=list(observation.annotations),
        )
        await self._own_admission(self._admit_input(observation))

    """Runtime Loop"""

    async def _handle_decision(self, event: PerceptionEvent) -> None:
        decision = TurnTakingDecision.from_annotation(event.annotation)
        if decision.action == TurnTakingAction.COMMIT:
            self._schedule_admission(self._admit_decision(event, decision))
        elif decision.action == TurnTakingAction.INTERRUPT:
            flags = self._candidate(decision.turn_candidate_id)
            if flags.intersection((TurnTakingAction.COMMIT, TurnTakingAction.INTERRUPT)):
                return

            flags.add(TurnTakingAction.INTERRUPT)
            foreground, reason = self._foreground, decision.reason or "avatar_directed_barge_in"
            if foreground is None or event.sequence <= foreground.cutoff_sequence:
                return

            self._cancel_foreground(foreground, reason)
            self._schedule_admission(self._interrupt_foreground(foreground, reason))

    async def _consume(self) -> None:
        perception = self._runtime.perception
        while True:
            await perception.wait_for_pending_annotations(consumer_id=self.CONSUMER_ID)
            batch = perception.take_pending_annotations(
                consumer_id=self.CONSUMER_ID,
                limit=1,
                predicate=lambda annotation: annotation.kind == AnnotationKind.INTERACTION_TURN,
            )
            if batch.has_gap:
                raise RuntimeError(f"Engine missed {batch.missed_count} turn decisions")
            for event in batch.items:
                await self._handle_decision(event)
            perception.commit_annotations(consumer_id=self.CONSUMER_ID, cursor_seq=batch.cursor_seq)

    """Runtime operations"""

    def notify_ready(self) -> None:
        if not self.ready:
            raise RuntimeError("Cannot announce an unready AvatarEngine")

        self._runtime.output.publish_execution(
            OutputExecutionSignal(
                scope=OutputScope(self._runtime.state.context_id),
                kind=ExecutionSignalKind.READY,
                state="ready",
            )
        )

        log_event(
            logger,
            "engine.ready",
            session_id=self._runtime.session.session_id,
            context_id=self._runtime.state.context_id,
            state="ready",
        )

    async def wait_failed(self) -> None:
        await self._failed.wait()
        raise RuntimeError("Native Avatar execution failed") from self._failure

    async def _start(self) -> None:
        if not self._loop.ready:
            raise RuntimeError("AvatarEngine cannot start with an unready Loop")

        await self._plugins.start()
        self._intake = asyncio.create_task(self._consume(), name=self.CONSUMER_ID)
        self._intake.add_done_callback(self._observe)
        await self._routers.start()
        self._ensure_open()
        self._ready = True

    async def on_start(self) -> None:
        self._ensure_open()
        if self._start_task is None:
            self._start_task = asyncio.create_task(self._start(), name="avatar_engine_start")
        try:
            await asyncio.shield(self._start_task)
            self._ensure_open()
        except BaseException as original:
            try:
                await self.on_stop()
            except BaseException as cleanup:
                raise original from cleanup
            raise

    async def _close(self) -> None:
        self._ready = False
        errors: list[Exception] = []
        if self._start_task is not None:
            if not self._start_task.done():
                self._start_task.cancel()
            await asyncio.gather(self._start_task, return_exceptions=True)
        if self._intake is not None:
            if not self._intake.done() and not self._intake.cancelling():
                self._intake_stopping = True
                self._intake.cancel()
            await asyncio.gather(self._intake, return_exceptions=True)
            self._observe(self._intake)
        pending = tuple(self._admissions)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
            for task in pending:
                self._observe(task)
        await self._step(
            lambda: self._interrupt_foreground(self._foreground, "engine_closed"),
            errors,
            "Output interruption",
        )
        # Execution producers settle while Memory, Status and output consumers are alive.
        await self._step(self._loop.aclose, errors, "Loop shutdown")
        if self._watchers:
            await asyncio.gather(*tuple(self._watchers), return_exceptions=True)
        await self._step(self._routers.stop, errors, "Router shutdown")
        await self._step(self._plugins.stop, errors, "Plugin shutdown")
        await self._step(
            lambda: self._runtime.perception.clear_annotation_consumer(self.CONSUMER_ID),
            errors,
            "Turn consumer retirement",
        )
        if self._failure is not None and self._failure not in errors:
            errors.insert(0, self._failure)
        if errors:
            raise ExceptionGroup("AvatarEngine shutdown failed", errors)

    def _ensure_close(self) -> asyncio.Task[None]:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="avatar_engine_close")
            self._close_task.add_done_callback(self._observe_close)
            try:
                self._cancel_foreground(self._foreground, "engine_closed")
            except BaseException as error:
                self._fail(error, "Immediate execution revocation")
        return self._close_task

    async def on_stop(self) -> None:
        await wait_for_cleanup(self._ensure_close())
