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
from alphaavatar.agents.router.enums import InteractionEntityKind, TurnTakingAction, TurnTakingMode
from alphaavatar.agents.router.schemas import TurnTakingDecision
from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.env.enums import AnnotationKind, ObservationKind
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
    from alphaavatar.core.turn.schemas import TurnNotice, TurnSnapshot

    from .loop import LoopHandle
    from .loop.base import ToolAuthorizer

_UNCERTAINTY_NOTICES = frozenset(
    ("router.speech_completion_uncertain", "router.addressing_uncertain")
)
_VISUAL_INPUTS = frozenset(
    (ObservationKind.IMAGE_INPUT, ObservationKind.VIDEO_FRAME, ObservationKind.SCREEN_FRAME)
)
# A Turn's modality by its turn-taking mode; any other mode is multimodal.
_MODALITIES = {
    TurnTakingMode.AUDIO_ONLY: TurnInputModality.AUDIO,
    TurnTakingMode.VISUAL_ONLY: TurnInputModality.IMAGE,
}


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
        runtime.capability_registry.collect(
            runtime.participants, self._memory, self._persona, *self._tool_plugins
        )

        # Step 3: bind memory and persona to runtime context.
        foundation.context.bind_sources(memory=self._memory, persona=self._persona)

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
        self._inputs: dict[str, set[TurnTakingAction]] = {}
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
    def _untranscribed(
        observations: tuple[EnvObservation, ...], notices: tuple[TurnNotice, ...]
    ) -> bool:
        """Whether the input is speech its notices say no transcript came from."""
        segments = {
            item.segment.segment_id
            for item in observations
            if item.kind == ObservationKind.SPEECH_SEGMENT and item.segment is not None
        }
        return bool(segments) and any(
            notice.code not in _UNCERTAINTY_NOTICES
            and (notice.code == "voice.transcription_unavailable" or notice.segment_ids)
            and set(notice.segment_ids) <= segments
            for notice in notices
        )

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

    def _input_flags(self, input_id: str) -> set[TurnTakingAction]:
        if not isinstance(input_id, str) or not input_id.strip() or len(input_id) > 512:
            raise ValueError("Turn input identity must contain 1..512 characters")

        flags = self._inputs.get(input_id)
        if flags is None:
            if len(self._inputs) >= self._config.max_turn_inputs:
                raise RuntimeError("Session turn admission capacity exhausted")

            flags = self._inputs[input_id] = set()
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

    def _entity(self, ref: InteractionEntityRef) -> TurnEntityRef:
        """An addressee, as admission finds it."""
        participant = self._runtime.participants.resolve(
            ref.device_id, source=ref.source, entity=ref.entity
        )
        # Perception labels are evidence; only the Session owns accepted user bindings.
        return TurnEntityRef(
            kind=ref.kind.value,
            participant_id=participant.participant_id if participant is not None else None,
            identity_revision=participant.identity_revision if participant is not None else None,
            user_id=participant.user_id if participant is not None else None,
            device_id=ref.device_id,
            entity=ref.entity,
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

    """Turn Action - Interrupt"""

    async def _interrupt_foreground(self, foreground: _Foreground | None, reason: str) -> None:
        self._cancel_foreground(foreground, reason)
        if foreground is not None:
            await self._runtime.output.interrupt(turn_id=foreground.turn_id, reason=reason)

    """Turn Action - Commit or Direct Input"""

    async def _submit(self, snapshot: TurnSnapshot) -> None:
        # Observe only committed input. No Run exists yet, and no prompt/history is logged.
        context_id = self._runtime.state.context_id
        log_event(
            logger,
            "input.committed",
            text=snapshot.text,
            session_id=self._runtime.session.session_id,
            context_id=context_id,
            turn_id=snapshot.turn_id,
            input_id=snapshot.input_id,
            modality=snapshot.modality.value,
        )
        previous, foreground = (
            self._foreground,
            _Foreground(snapshot.turn_id, context_id, snapshot.cutoff.sequence),
        )
        self._foreground = foreground
        await self._interrupt_foreground(previous, "superseded")

        await self._runtime.output.start_turn(turn_id=snapshot.turn_id)
        if foreground.interrupted or self._close_task is not None:
            return

        if self._runtime.state.context_id != context_id:
            raise RuntimeError("Context changed during Turn admission")

        request = LoopRequest(
            turn=snapshot,
            context_id=context_id,
            allowed_capabilities=tuple(
                capability.id for capability in self._runtime.capability_registry.capabilities
            )
            if snapshot.modality != TurnInputModality.SYSTEM
            else (),
            limits=self._config.loop_limits,
            depth=self._config.depth,
        )
        handle = await self._loop.submit(request, authorize=self._authorize)
        foreground.handle = handle

        # A different Loop implementation may suspend while accepting the request.
        if foreground.interrupted or self._close_task is not None:
            await self._interrupt_foreground(foreground, "interrupted_during_admission")

        task = asyncio.create_task(self._watch(handle), name=f"avatar_run:{handle.identity.run_id}")
        self._watchers.add(task)
        task.add_done_callback(self._watchers.discard)
        task.add_done_callback(self._observe)

    def _log_participants(self, snapshot: TurnSnapshot) -> None:
        """The Turn's participants as admission finds them, and where each of its segments'
        association stands then: a pending one settles later, as its own line says, and
        counts for whoever reads the Turn's participants after that."""
        participants = self._runtime.participants
        listed = ",".join(
            f"{entry.participant_id}/{entry.user_id or '-'}/r{entry.identity_revision}"
            if entry.participant_id is not None
            else "unattributed"
            for entry in participants.of_turn(snapshot)
        )
        inputs = set(snapshot.input_observation_ids)
        segments = ",".join(
            f"{segment.segment_id}:{participants.segment_association(segment)}"
            for segment in dict.fromkeys(
                event.observation.segment
                for event in snapshot.perception_events
                if event.observation is not None
                and event.observation.observation_id in inputs
                and event.observation.segment is not None
            )
        )
        logger.info(
            "Turn participants turn_id=%s input_id=%s participants=%s segments=%s",
            snapshot.turn_id,
            snapshot.input_id,
            listed or "none",
            segments or "none",
        )

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
            input_id=decision.input_id,
            revision=decision.revision,
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

    def _refuse(
        self,
        event: PerceptionEvent,
        decision: TurnTakingDecision,
        flags: set[TurnTakingAction],
        reason: str,
        *,
        rejected: bool = False,
        evidence: tuple[EnvObservation | None, ...] = (),
    ) -> None:
        """Close the input this decision cannot admit. A stale decision is ignored; one whose
        evidence is lost or says nothing is rejected, which freezes the trace."""
        flags.add(TurnTakingAction.CANCEL)
        self._trace_admission(
            event,
            decision,
            outcome="rejected" if rejected else "ignored",
            reason=reason,
            evidence_count=len(evidence),
            missing_count=sum(value is None for value in evidence),
        )

    def _admission_expired(
        self, event: PerceptionEvent, decision: TurnTakingDecision, flags: set[TurnTakingAction]
    ) -> bool:
        deadline = event.annotation.data.get("admission_deadline_ns")
        if deadline is None:
            return False
        if type(deadline) is int and self._runtime.clock.now().monotonic_ns < deadline:
            return False
        reason = "admission_expired" if type(deadline) is int else "admission_deadline_invalid"
        self._refuse(event, decision, flags, reason)
        return True

    def _answerable(
        self, decision: TurnTakingDecision, observations: tuple[EnvObservation, ...]
    ) -> bool:
        """Whether a Turn of notices alone can still be answered: the Avatar has output, no one
        is speaking, the speech was or may have been for the Avatar, and its source is still the
        participants' current one. Admission has already refused a retired speech source."""
        interaction = self._runtime.state.interaction_method
        return (
            (interaction.text_output or interaction.audio_output)
            and not self._runtime.perception.has_active_speech
            and (
                "router.addressing_uncertain" in {notice.code for notice in decision.system_notices}
                or any(ref.kind == InteractionEntityKind.AVATAR for ref in decision.addressees)
            )
            and all(
                self._runtime.participants.source_is_current(item.segment.source)
                for item in observations
                if item.kind == ObservationKind.SPEECH_SEGMENT and item.segment is not None
            )
        )

    async def _admit_decision(self, event: PerceptionEvent, decision: TurnTakingDecision) -> None:
        async with self._admission_lock:
            if self._close_task is not None:
                raise TurnAdmissionRejected("Engine closed before Turn admission")

            # A stale decision: its input is closed, its deadline or context has passed, or a
            # later Turn covers it already.
            flags = self._input_flags(decision.input_id)
            if flags.intersection((TurnTakingAction.COMMIT, TurnTakingAction.CANCEL)):
                self._trace_admission(event, decision, outcome="ignored", reason="input_terminal")
                return
            if self._admission_expired(event, decision, flags):
                return
            context_id = event.annotation.data.get("context_id", self._runtime.state.context_id)
            if self._runtime.state.context_id != context_id:
                self._refuse(event, decision, flags, "context_changed")
                return
            latest = self._runtime.turn.latest
            if latest is not None and event.sequence <= latest.cutoff.sequence:
                flags.add(TurnTakingAction.COMMIT)
                logger.info("Skipped superseded turn decision input_id=%s", decision.input_id)
                self._trace_admission(event, decision, outcome="ignored", reason="superseded")
                return

            # Its evidence. This is a proposed Turn, not an admitted one: reject the proposed
            # input; never substitute newer evidence or kill a healthy session after retention loss.
            evidence = tuple(
                self._runtime.perception.timeline.get_observation(observation_id=value)
                for value in dict.fromkeys(decision.input_observation_ids)
            )
            if not evidence or any(value is None for value in evidence):
                logger.warning(
                    "Turn admission rejected input_id=%s reason=evidence_unavailable "
                    "decision_sequence=%s evidence_count=%s missing_count=%s",
                    decision.input_id,
                    event.sequence,
                    len(evidence),
                    sum(value is None for value in evidence),
                )
                self._refuse(
                    event, decision, flags, "evidence_unavailable", rejected=True, evidence=evidence
                )
                return

            observations = tuple(
                sorted(evidence, key=lambda value: value.time_range.start.monotonic_ns)
            )
            if any(
                item.segment is not None
                and not self._runtime.perception.speech_source_is_current(item.segment.source)
                for item in observations
            ):
                self._refuse(event, decision, flags, "speech_source_retired")
                return

            started_at = observations[0].time_range.start
            if (
                latest is not None
                and latest.metadata.get("source") == "avatar.engine.direct"
                and started_at.monotonic_ns < latest.committed_at.monotonic_ns
            ):
                self._refuse(event, decision, flags, "superseded")
                return

            # What it says: words or pictures, or else the notices of speech no transcript came
            # from, while those can still be answered.
            text = self._text(observations)
            has_input = text is not None or any(
                item.kind in _VISUAL_INPUTS for item in observations
            )
            notice_only = not has_input and self._untranscribed(
                observations, decision.system_notices
            )
            if notice_only and not self._answerable(decision, observations):
                self._refuse(event, decision, flags, "notice_superseded")
                return
            if not (has_input or notice_only):
                logger.info(
                    "Turn admission rejected input_id=%s reason=no_usable_input", decision.input_id
                )
                self._refuse(
                    event, decision, flags, "no_usable_input", rejected=True, evidence=observations
                )
                return

            addressees = tuple(self._entity(ref) for ref in decision.addressees)
            if self._admission_expired(event, decision, flags):
                return

            flags.add(TurnTakingAction.COMMIT)
            snapshot = self._runtime.turn.commit_event_input(
                input_id=decision.input_id,
                modality=TurnInputModality.SYSTEM
                if notice_only
                else _MODALITIES.get(decision.turn_mode, TurnInputModality.MULTIMODAL),
                text=text,
                started_at=started_at,
                committed_at=event.time_range.end,
                cutoff_sequence=event.sequence,
                input_observation_ids=decision.input_observation_ids,
                addressees=addressees,
                context_ids=(context_id,),
                metadata={
                    "revision": decision.revision,
                    "decision_event_id": event.event_id,
                    "decision_event_sequence": event.sequence,
                    "decision_annotation_id": event.annotation.annotation_id,
                    "reason": decision.reason,
                },
                system_notices=decision.system_notices,
            )
            self._log_participants(snapshot)
            self._trace_admission(
                event,
                decision,
                outcome="accepted",
                reason="system_notice" if notice_only else "committed",
                evidence_count=len(observations),
            )
            await self._submit(snapshot)

    async def _admit_input(self, observation: EnvObservation) -> None:
        async with self._admission_lock:
            if self._close_task is not None:
                raise TurnAdmissionRejected("Engine closed before Turn admission")

            flags = self._input_flags(observation.observation_id)
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
                context_ids=(self._runtime.state.context_id,),
                metadata={"source": "avatar.engine.direct"},
            )
            self._log_participants(snapshot)
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
            if (
                event.annotation.data.get("context_id", self._runtime.state.context_id)
                != self._runtime.state.context_id
            ):
                return

            flags = self._input_flags(decision.input_id)
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
