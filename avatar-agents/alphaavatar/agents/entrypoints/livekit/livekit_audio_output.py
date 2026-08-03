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
"""LiveKit transport adapter for AlphaAvatar output audio."""

from __future__ import annotations

import asyncio

from alphaavatar.agents.log import logger
from alphaavatar.agents.plugin import AvatarRuntimePlugin
from alphaavatar.core.media import AudioFrame
from alphaavatar.core.output import (
    OutputControl,
    OutputControlType,
    OutputEvent,
    OutputKind,
    OutputLane,
    OutputPlaybackType,
    OutputRuntime,
    OutputSubscription,
)
from livekit import rtc


class LiveKitTransientAudioOutput(AvatarRuntimePlugin):
    """
    Publish transient audio and report actual transport playout progress.

    Audio production and transport playout are separate:
    - AUDIO_FRAME means audio was produced.
    - PLAYBACK reports how much audio was actually played or interrupted.
    """

    def __init__(
        self,
        *,
        room: rtc.Room,
        output_runtime: OutputRuntime,
        sample_rate: int,
        num_channels: int,
        track_name: str = "alphaavatar_transient_audio",
        queue_size_ms: int = 100,
        progress_interval_sec: float = 0.1,
        subscription_name: str = "livekit:transient_audio",
    ) -> None:
        if progress_interval_sec <= 0:
            raise ValueError("progress_interval_sec must be positive")

        self._room = room
        self._output = output_runtime
        self._sample_rate = sample_rate
        self._num_channels = num_channels
        self._track_name = track_name
        self._queue_size_ms = queue_size_ms
        self._progress_interval_sec = progress_interval_sec
        self._subscription_name = subscription_name

        self._source: rtc.AudioSource | None = None
        self._track: rtc.LocalAudioTrack | None = None
        self._publication_sid: str | None = None
        self._subscription: OutputSubscription | None = None
        self._run_task: asyncio.Task[None] | None = None
        self._playout_task: asyncio.Task[None] | None = None

        self._active_output_id: str | None = None
        self._active_turn_id: str | None = None
        self._generation = 0

        self._pushed_duration_sec = 0.0
        self._last_reported_played_sec = 0.0
        self._playback_started = False

    @property
    def track_sid(self) -> str | None:
        return self._publication_sid

    async def on_session_start(self) -> None:
        if self._run_task is not None:
            return

        source = rtc.AudioSource(
            sample_rate=self._sample_rate,
            num_channels=self._num_channels,
            queue_size_ms=self._queue_size_ms,
        )
        track = rtc.LocalAudioTrack.create_audio_track(self._track_name, source)

        options = rtc.TrackPublishOptions()
        options.source = rtc.TrackSource.SOURCE_MICROPHONE

        publication = await self._room.local_participant.publish_track(track, options)
        subscription = await self._output.stream.subscribe(
            self._subscription_name,
            kinds=(OutputKind.AUDIO_FRAME, OutputKind.CONTROL),
            lanes=(OutputLane.TRANSIENT,),
            max_pending=256,
            reliable=True,
        )

        self._source = source
        self._track = track
        self._publication_sid = publication.sid
        self._subscription = subscription
        self._run_task = asyncio.create_task(self._run(), name=self._subscription_name)

        logger.info(
            "Published transient audio track name=%s sid=%s sample_rate=%s channels=%s",
            self._track_name,
            publication.sid,
            self._sample_rate,
            self._num_channels,
        )

    async def on_session_stop(self) -> None:
        run_task = self._run_task
        self._run_task = None

        if run_task is not None and not run_task.done():
            run_task.cancel()
        if run_task is not None:
            await asyncio.gather(run_task, return_exceptions=True)

        output_id = self._active_output_id
        if output_id is not None and self._output.is_active(output_id):
            await self._output.interrupt(
                lane=OutputLane.TRANSIENT,
                output_id=output_id,
                reason="livekit_audio_output_stopping",
            )

        await self._interrupt("session_stopping")

        if self._subscription is not None:
            await self._output.stream.unsubscribe(self._subscription_name)

        source = self._source
        publication_sid = self._publication_sid

        if source is not None:
            source.clear_queue()

        if publication_sid is not None:
            try:
                await self._room.local_participant.unpublish_track(publication_sid)
            except Exception as exc:
                logger.debug("Failed to unpublish transient audio track: %s", exc)

        if source is not None:
            await source.aclose()

        self._source = None
        self._track = None
        self._publication_sid = None
        self._subscription = None
        self._reset_active()
        self._generation += 1

    async def _run(self) -> None:
        subscription = self._subscription
        if subscription is None:
            return

        try:
            while True:
                event = await subscription.get()

                try:
                    if event.kind == OutputKind.AUDIO_FRAME:
                        await self._handle_audio(event)
                    elif event.kind == OutputKind.CONTROL:
                        await self._handle_control(event)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Failed to process LiveKit audio output event "
                        "event_id=%s output_id=%s kind=%s",
                        event.event_id,
                        event.output_id,
                        event.kind,
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("LiveKit transient audio output stopped unexpectedly.")

    async def _handle_audio(self, event: OutputEvent) -> None:
        frame = event.payload
        output_id = event.output_id

        if not isinstance(frame, AudioFrame) or output_id is None:
            return

        if frame.sample_rate != self._sample_rate:
            raise ValueError(
                f"Transient audio sample-rate mismatch: "
                f"expected={self._sample_rate}, actual={frame.sample_rate}"
            )

        if frame.num_channels != self._num_channels:
            raise ValueError(
                f"Transient audio channel mismatch: "
                f"expected={self._num_channels}, actual={frame.num_channels}"
            )

        if output_id != self._active_output_id:
            await self._activate_output(event)

        source = self._require_source()
        generation = self._generation

        await source.capture_frame(
            rtc.AudioFrame(
                data=frame.data,
                sample_rate=frame.sample_rate,
                num_channels=frame.num_channels,
                samples_per_channel=frame.samples_per_channel,
            )
        )

        if generation != self._generation or output_id != self._active_output_id:
            source.clear_queue()
            return

        self._pushed_duration_sec += frame.samples_per_channel / frame.sample_rate

        queued_duration_sec = self._queued_duration(source)
        played_duration_sec = max(self._pushed_duration_sec - queued_duration_sec, 0.0)

        if not self._playback_started:
            self._playback_started = True
            self._last_reported_played_sec = played_duration_sec

            await self._report_playback(
                playback_type=OutputPlaybackType.STARTED,
                output_id=output_id,
                turn_id=event.turn_id,
                played_duration_sec=played_duration_sec,
                queued_duration_sec=queued_duration_sec,
            )
            return

        if played_duration_sec - self._last_reported_played_sec >= self._progress_interval_sec:
            self._last_reported_played_sec = played_duration_sec

            await self._report_playback(
                playback_type=OutputPlaybackType.PROGRESS,
                output_id=output_id,
                turn_id=event.turn_id,
                played_duration_sec=played_duration_sec,
                queued_duration_sec=queued_duration_sec,
            )

    async def _activate_output(self, event: OutputEvent) -> None:
        output_id = event.output_id
        if output_id is None:
            return

        previous_output_id = self._active_output_id
        if previous_output_id is not None and previous_output_id != output_id:
            if self._output.is_active(previous_output_id):
                await self._output.interrupt(
                    lane=OutputLane.TRANSIENT,
                    output_id=previous_output_id,
                    reason="replaced_by_new_audio_output",
                )

            await self._interrupt("replaced_by_new_audio_output")

        source = self._require_source()
        source.clear_queue()

        self._generation += 1
        self._active_output_id = output_id
        self._active_turn_id = event.turn_id
        self._pushed_duration_sec = 0.0
        self._last_reported_played_sec = 0.0
        self._playback_started = False

    async def _handle_control(self, event: OutputEvent) -> None:
        control = event.payload
        if not isinstance(control, OutputControl) or not self._matches_control(control):
            return

        if control.type == OutputControlType.INTERRUPT:
            await self._interrupt(control.reason)
        elif control.type == OutputControlType.COMPLETE:
            await self._start_playout_waiter()

    def _matches_control(self, control: OutputControl) -> bool:
        if control.target_lane is not None and control.target_lane != OutputLane.TRANSIENT:
            return False
        if (
            control.target_output_id is not None
            and control.target_output_id != self._active_output_id
        ):
            return False
        if control.target_turn_id is not None and control.target_turn_id != self._active_turn_id:
            return False
        return True

    async def _interrupt(self, reason: str) -> None:
        await self._cancel_playout()

        output_id = self._active_output_id
        turn_id = self._active_turn_id
        source = self._source

        queued_duration_sec = self._queued_duration(source)
        pushed_duration_sec = self._pushed_duration_sec
        played_duration_sec = max(pushed_duration_sec - queued_duration_sec, 0.0)

        self._generation += 1
        self._reset_active()

        if source is not None:
            source.clear_queue()

        if output_id is not None:
            await self._report_playback(
                playback_type=OutputPlaybackType.INTERRUPTED,
                output_id=output_id,
                turn_id=turn_id,
                played_duration_sec=played_duration_sec,
                pushed_duration_sec=pushed_duration_sec,
                queued_duration_sec=queued_duration_sec,
                reason=reason,
            )

        logger.debug(
            "Interrupted transient LiveKit audio output_id=%s "
            "played=%.3f pushed=%.3f queued=%.3f reason=%s",
            output_id,
            played_duration_sec,
            pushed_duration_sec,
            queued_duration_sec,
            reason,
        )

    async def _start_playout_waiter(self) -> None:
        await self._cancel_playout()

        output_id = self._active_output_id
        turn_id = self._active_turn_id
        generation = self._generation
        pushed_duration_sec = self._pushed_duration_sec
        source = self._source

        if output_id is None or source is None:
            return

        async def _wait() -> None:
            try:
                await source.wait_for_playout()

                if generation != self._generation or output_id != self._active_output_id:
                    return

                await self._report_playback(
                    playback_type=OutputPlaybackType.FINISHED,
                    output_id=output_id,
                    turn_id=turn_id,
                    played_duration_sec=pushed_duration_sec,
                    pushed_duration_sec=pushed_duration_sec,
                    queued_duration_sec=0.0,
                )

                if generation == self._generation and output_id == self._active_output_id:
                    self._reset_active()

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Failed while waiting for transient audio playout output_id=%s",
                    output_id,
                )

        self._playout_task = asyncio.create_task(
            _wait(),
            name=f"livekit:transient_playout:{output_id}",
        )

    async def _report_playback(
        self,
        *,
        playback_type: OutputPlaybackType,
        output_id: str,
        turn_id: str | None,
        played_duration_sec: float,
        queued_duration_sec: float,
        pushed_duration_sec: float | None = None,
        reason: str | None = None,
    ) -> None:
        try:
            await self._output.publish_playback(
                output_id=output_id,
                lane=OutputLane.TRANSIENT,
                turn_id=turn_id,
                playback_type=playback_type,
                played_duration_sec=max(played_duration_sec, 0.0),
                pushed_duration_sec=max(
                    self._pushed_duration_sec
                    if pushed_duration_sec is None
                    else pushed_duration_sec,
                    0.0,
                ),
                queued_duration_sec=max(queued_duration_sec, 0.0),
                metadata={
                    "transport": "livekit",
                    "track_sid": self._publication_sid,
                    **({"reason": reason} if reason else {}),
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to report LiveKit playback output_id=%s type=%s",
                output_id,
                playback_type,
            )

    async def _cancel_playout(self) -> None:
        task = self._playout_task
        self._playout_task = None

        if task is not None and not task.done():
            task.cancel()

        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    def _reset_active(self) -> None:
        self._active_output_id = None
        self._active_turn_id = None
        self._pushed_duration_sec = 0.0
        self._last_reported_played_sec = 0.0
        self._playback_started = False

    def _require_source(self) -> rtc.AudioSource:
        if self._source is None:
            raise RuntimeError("LiveKit transient audio output is not started")
        return self._source

    @staticmethod
    def _queued_duration(source: rtc.AudioSource | None) -> float:
        if source is None:
            return 0.0

        try:
            return max(float(getattr(source, "queued_duration", 0.0) or 0.0), 0.0)
        except (TypeError, ValueError):
            return 0.0
