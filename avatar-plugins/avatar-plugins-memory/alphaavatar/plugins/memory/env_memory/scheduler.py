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
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass, field
from typing import Any

from livekit.agents.llm import ChatItem

from alphaavatar.agents.avatar.prompting import MemoryPluginsTemplate
from alphaavatar.agents.constants import VIDEO_MEMORY_INTERVAL_SEC
from alphaavatar.agents.memory import MemoryCache
from alphaavatar.core.env import EnvObservation
from alphaavatar.core.perception import PerceptionRuntime

from ..log import logger

DEFAULT_ENV_MEMORY_INTERVAL_SEC = 30.0
DEFAULT_ANNOTATION_GRACE_SEC = 0.75
DEFAULT_CONSUMER_ID = "memory.env"
DEFAULT_PROCESS_TIMEOUT_SEC = 25.0
DEFAULT_DRAIN_TIMEOUT_SEC = 35.0
DEFAULT_RETRY_DELAY_SEC = 0.5
DEFAULT_MAX_ATTEMPTS = 2
DEFAULT_STREAMS = ("video", "screen")

_VISUAL_KINDS = {
    "video_frame",
    "screen_frame",
}


@dataclass(slots=True)
class EnvMemoryBatch:
    session_id: str
    observations: list[EnvObservation]
    conversation_context: str | None
    triggers: set[str] = field(default_factory=set)

    raw_observation_count: int = 0
    message_count: int = 0
    missed_count: int = 0
    attempts: int = 0

    @property
    def trigger_text(self) -> str:
        return ",".join(sorted(self.triggers))

    def build_evidence(self) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []

        for observation in self.observations:
            item = observation.to_evidence_dict()

            if item:
                evidence.append(item)

        return evidence

    def merge(self, other: EnvMemoryBatch) -> None:
        if self.session_id != other.session_id:
            raise ValueError("Cannot merge ENV memory batches from different sessions")

        existing_ids = {observation.observation_id for observation in self.observations}

        for observation in other.observations:
            if observation.observation_id in existing_ids:
                continue

            existing_ids.add(observation.observation_id)
            self.observations.append(observation)

        contexts = [
            context
            for context in (
                self.conversation_context,
                other.conversation_context,
            )
            if context
        ]

        self.conversation_context = "\n\n".join(contexts) if contexts else None

        self.triggers.update(other.triggers)
        self.raw_observation_count += other.raw_observation_count
        self.message_count += other.message_count
        self.missed_count += other.missed_count


ProcessCallback = Callable[
    [EnvMemoryBatch, float],
    Awaitable[object],
]


class EnvMemoryScheduler:
    """
    Schedule ENV Memory captures and serialize extraction.

    Perception delivery and model extraction are intentionally separated:

    - capture quickly takes ownership of observations and advances the cursor;
    - processing runs asynchronously and never blocks future captures;
    - at most one batch is processed and one pending batch is accumulated.
    """

    def __init__(
        self,
        *,
        perception_runtime: PerceptionRuntime,
        memory_cache: MemoryCache,
        process: ProcessCallback,
        streams: Collection[str] | None = None,
        interval_sec: float = DEFAULT_ENV_MEMORY_INTERVAL_SEC,
        annotation_grace_sec: float = DEFAULT_ANNOTATION_GRACE_SEC,
        consumer_id: str = DEFAULT_CONSUMER_ID,
        video_sample_interval_sec: float = VIDEO_MEMORY_INTERVAL_SEC,
        process_timeout_sec: float = DEFAULT_PROCESS_TIMEOUT_SEC,
        drain_timeout_sec: float = DEFAULT_DRAIN_TIMEOUT_SEC,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_delay_sec: float = DEFAULT_RETRY_DELAY_SEC,
    ) -> None:
        if interval_sec <= 0:
            raise ValueError("interval_sec must be positive")

        if annotation_grace_sec < 0:
            raise ValueError("annotation_grace_sec cannot be negative")

        if process_timeout_sec <= 0:
            raise ValueError("process_timeout_sec must be positive")

        if drain_timeout_sec <= 0:
            raise ValueError("drain_timeout_sec must be positive")

        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")

        resolved_streams = frozenset(streams or DEFAULT_STREAMS)

        if not resolved_streams:
            raise ValueError("ENV Memory streams cannot be empty")

        self._perception_runtime = perception_runtime
        self._memory_cache = memory_cache
        self._process = process

        self._streams = resolved_streams
        self._interval_sec = interval_sec
        self._annotation_grace_sec = annotation_grace_sec
        self._consumer_id = consumer_id
        self._video_sample_interval_sec = video_sample_interval_sec
        self._process_timeout_sec = process_timeout_sec
        self._drain_timeout_sec = drain_timeout_sec
        self._max_attempts = max_attempts
        self._retry_delay_sec = retry_delay_sec

        self._last_visual_sample_ts_by_source: dict[str, float] = {}

        self._requested_triggers: set[str] = set()
        self._wake_event = asyncio.Event()

        # One active batch may be under inference and one pending batch may
        # accumulate newer observations.
        self._pending_batch: EnvMemoryBatch | None = None

        self._scheduler_task: asyncio.Task[None] | None = None
        self._processor_task: asyncio.Task[None] | None = None

        self._stopping = False

    @property
    def session_id(self) -> str:
        return self._memory_cache.session_id

    @property
    def streams(self) -> frozenset[str]:
        return self._streams

    @property
    def interval_sec(self) -> float:
        return self._interval_sec

    @property
    def annotation_grace_sec(self) -> float:
        return self._annotation_grace_sec

    def request(self, trigger: str) -> None:
        """
        Request an immediate capture.

        A request only resets the periodic deadline when a batch containing
        actual visual or audio observations is captured.
        """

        if self._stopping:
            return

        normalized = trigger.strip()

        if not normalized:
            return

        self._requested_triggers.add(normalized)
        self._wake_event.set()

    def _take_requested_triggers(self) -> set[str]:
        self._wake_event.clear()

        triggers = self._requested_triggers
        self._requested_triggers = set()

        return triggers

    @staticmethod
    def _build_conversation_context(messages: list[ChatItem]) -> str | None:
        if not messages:
            return None

        context = MemoryPluginsTemplate.apply_search_template(
            messages,
            filter_roles=["system"],
        )

        return context or None

    @staticmethod
    def _is_environment_observation(observation: EnvObservation) -> bool:
        """
        Only visual/audio evidence can create an ENV Memory batch.

        User text is carried separately as conversation context and never
        qualifies as environment evidence by itself.
        """

        if observation.kind in _VISUAL_KINDS:
            return observation.payload is not None

        if observation.kind == "audio_segment":
            return observation.payload is not None

        # Raw audio frames are too frequent and do not directly contain
        # retrievable semantic information.
        if observation.kind == "audio_frame":
            return False

        # Future audio/vision classifiers may publish lightweight semantic
        # observations without media payloads.
        metadata = observation.metadata or {}

        return metadata.get("env_memory_eligible") is True and metadata.get("modality") in {
            "audio",
            "vision",
        }

    def _sample_observations(
        self,
        observations: list[EnvObservation],
    ) -> tuple[list[EnvObservation], dict[str, float]]:
        sampled: list[EnvObservation] = []
        visual_timestamp_updates: dict[str, float] = {}

        for observation in observations:
            if not self._is_environment_observation(observation):
                continue

            if observation.kind not in _VISUAL_KINDS:
                sampled.append(observation)
                continue

            if self._video_sample_interval_sec <= 0:
                sampled.append(observation)
                continue

            try:
                timestamp = float(observation.timestamp)
            except (TypeError, ValueError):
                sampled.append(observation)
                continue

            source_id = observation.source_id or observation.frame_id or "default"

            last_timestamp = visual_timestamp_updates.get(
                source_id,
                self._last_visual_sample_ts_by_source.get(source_id),
            )

            if (
                last_timestamp is not None
                and timestamp - last_timestamp < self._video_sample_interval_sec
            ):
                continue

            visual_timestamp_updates[source_id] = timestamp
            sampled.append(observation)

        return sampled, visual_timestamp_updates

    async def _capture_batch(
        self,
        triggers: set[str],
    ) -> EnvMemoryBatch | None:
        window = self._perception_runtime.take_pending_observations(
            consumer_id=self._consumer_id,
            streams=set(self._streams),
            require_payload=False,
            min_age_sec=self._annotation_grace_sec,
        )

        should_commit_window = False

        try:
            raw_observations = list(window.observations)

            if window.has_gap:
                logger.warning(
                    "[Memory] ENV perception gap sid=%s triggers=%s missed=%s",
                    self.session_id,
                    sorted(triggers),
                    window.missed_count,
                )

            if not raw_observations:
                should_commit_window = True
                return None

            observations, visual_timestamp_updates = self._sample_observations(raw_observations)

            # No visual/audio observation means no ENV Memory update.
            # Pending text messages remain uncommitted and may be attached to a
            # future batch that contains real environmental evidence.
            if not observations:
                should_commit_window = True

                logger.debug(
                    "[Memory] ENV capture skipped after sampling "
                    "sid=%s triggers=%s raw_observations=%s",
                    self.session_id,
                    sorted(triggers),
                    len(raw_observations),
                )
                return None

            messages = list(self._memory_cache.take_pending_env_messages())

            conversation_context = self._build_conversation_context(messages)

            batch = EnvMemoryBatch(
                session_id=self.session_id,
                observations=observations,
                conversation_context=conversation_context,
                triggers=set(triggers),
                raw_observation_count=len(raw_observations),
                message_count=len(messages),
                missed_count=(window.missed_count if window.has_gap else 0),
            )

            # The local batch now owns the observation references and rendered
            # conversation context.
            self._memory_cache.commit_env_messages()
            self._last_visual_sample_ts_by_source.update(visual_timestamp_updates)

            should_commit_window = True

            logger.debug(
                "[Memory] ENV batch captured sid=%s triggers=%s "
                "observations=%s raw_observations=%s messages=%s",
                self.session_id,
                sorted(triggers),
                len(observations),
                len(raw_observations),
                len(messages),
            )

            return batch

        finally:
            # Only acknowledge delivery when observations were filtered or
            # successfully transferred into a local batch.
            if should_commit_window:
                self._perception_runtime.commit_observations(window)

    def _enqueue_batch(self, batch: EnvMemoryBatch) -> None:
        if self._pending_batch is None:
            self._pending_batch = batch
        else:
            self._pending_batch.merge(batch)

        if self._processor_task is None or self._processor_task.done():
            self._processor_task = asyncio.create_task(
                self._processor_loop(),
                name=f"memory_env_processor:{self.session_id}",
            )

    async def _capture_and_enqueue(self, triggers: set[str]) -> bool:
        if not triggers:
            return False

        try:
            batch = await self._capture_batch(triggers)

            if batch is None:
                return False

            self._enqueue_batch(batch)
            return True

        except asyncio.CancelledError:
            raise

        except Exception:
            logger.exception(
                "[Memory] ENV capture failed sid=%s triggers=%s",
                self.session_id,
                sorted(triggers),
            )
            return False

    async def _scheduler_loop(self) -> None:
        loop = asyncio.get_running_loop()
        next_periodic_at = loop.time() + self._interval_sec

        while True:
            try:
                timeout = max(0.0, next_periodic_at - loop.time())

                try:
                    await asyncio.wait_for(
                        self._wake_event.wait(),
                        timeout=timeout,
                    )

                except asyncio.TimeoutError:
                    triggers = {"periodic"}

                    # A user trigger may arrive at the same moment as the
                    # periodic deadline.
                    if self._wake_event.is_set():
                        triggers.update(self._take_requested_triggers())

                    await self._capture_and_enqueue(triggers)

                    # A periodic tick always starts a new period.
                    next_periodic_at = loop.time() + self._interval_sec
                    continue

                triggers = self._take_requested_triggers()
                captured = await self._capture_and_enqueue(triggers)

                # User-triggered text only refreshes the period when actual
                # visual/audio evidence produced an ENV batch.
                if captured:
                    next_periodic_at = loop.time() + self._interval_sec

            except asyncio.CancelledError:
                raise

            except Exception:
                logger.exception(
                    "[Memory] ENV scheduler failed sid=%s",
                    self.session_id,
                )
                await asyncio.sleep(0.05)

    async def _processor_loop(self) -> None:
        while self._pending_batch is not None:
            batch = self._pending_batch
            self._pending_batch = None

            try:
                while True:
                    try:
                        await self._process(
                            batch,
                            self._process_timeout_sec,
                        )
                        break

                    except asyncio.CancelledError:
                        raise

                    except Exception:
                        batch.attempts += 1

                        if batch.attempts >= self._max_attempts:
                            logger.exception(
                                "[Memory] ENV batch dropped after retries "
                                "sid=%s attempts=%s triggers=%s "
                                "observations=%s",
                                batch.session_id,
                                batch.attempts,
                                sorted(batch.triggers),
                                len(batch.observations),
                            )
                            break

                        logger.warning(
                            "[Memory] ENV processing failed; retrying "
                            "sid=%s attempt=%s triggers=%s "
                            "observations=%s",
                            batch.session_id,
                            batch.attempts,
                            sorted(batch.triggers),
                            len(batch.observations),
                            exc_info=True,
                        )

                        await asyncio.sleep(self._retry_delay_sec)

            except asyncio.CancelledError:
                # Keep the active batch ahead of newer pending evidence.
                if self._pending_batch is not None:
                    batch.merge(self._pending_batch)

                self._pending_batch = batch
                raise

    async def start(self) -> None:
        if self._scheduler_task is not None and not self._scheduler_task.done():
            return

        self._stopping = False

        self._scheduler_task = asyncio.create_task(
            self._scheduler_loop(),
            name=f"memory_env_scheduler:{self.session_id}",
        )

    async def stop(self) -> None:
        self._stopping = True

        if self._scheduler_task is not None:
            self._scheduler_task.cancel()

            await asyncio.gather(
                self._scheduler_task,
                return_exceptions=True,
            )

            self._scheduler_task = None

        await self._capture_and_enqueue({"session_stop"})

        task = self._processor_task

        if task is not None and not task.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(task),
                    timeout=self._drain_timeout_sec,
                )

            except asyncio.TimeoutError:
                logger.warning(
                    "[Memory] ENV processor drain timed out sid=%s pending_batch=%s",
                    self.session_id,
                    self._pending_batch is not None,
                )

                task.cancel()

                await asyncio.gather(
                    task,
                    return_exceptions=True,
                )

        self._processor_task = None

        if self._pending_batch is not None:
            logger.warning(
                "[Memory] ENV pending batch abandoned during shutdown "
                "sid=%s triggers=%s observations=%s",
                self._pending_batch.session_id,
                sorted(self._pending_batch.triggers),
                len(self._pending_batch.observations),
            )
            self._pending_batch = None

        self._last_visual_sample_ts_by_source.clear()
