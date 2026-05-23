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
import time
from collections import deque

from livekit import rtc
from livekit.agents import get_job_context, llm

from alphaavatar.agents.avatar.vision.base import VisionBase
from alphaavatar.agents.configs.plugins.vision_plugin_config import VisionInputMode
from alphaavatar.agents.log import logger

from .constants import (
    LATEST_VIDEO_FRAME_LABEL,
    VIDEO_FRAME_LABEL_PREFIX,
    VISUAL_INPUT_PREFIX,
)


class SampledFrameVision(VisionBase):
    """Sampled-frame visual input from LiveKit video tracks.

    This strategy:
    1. listens to LiveKit video tracks,
    2. reads frames via rtc.VideoStream,
    3. samples frames into a bounded buffer,
    4. injects selected frames into the latest user message before LLM inference.
    """

    def __init__(self, agent) -> None:
        super().__init__(agent)

        vision_config = self.agent.avatar_config.vision_plugin_config

        self._video_frame_buffer: deque[rtc.VideoFrame] = deque(
            maxlen=vision_config.vision_frame_buffer_size
        )
        self._last_video_frame_sample_ts: float = 0.0

        self._video_streams: dict[str, rtc.VideoStream] = {}
        self._video_tasks: set[asyncio.Task[None]] = set()

        self._listeners_registered: bool = False

    def _try_attach_existing_video_tracks(self) -> None:
        try:
            room = get_job_context().room
        except Exception as e:
            logger.warning("Cannot access LiveKit room for video input: %s", e)
            return

        for participant in room.remote_participants.values():
            for publication in participant.track_publications.values():
                track = publication.track
                if track is None:
                    continue

                if track.kind != rtc.TrackKind.KIND_VIDEO:
                    continue

                self._create_video_stream(
                    track=track,
                    track_sid=publication.sid,
                    participant_identity=participant.identity,
                )

    def _register_video_track_listeners(self) -> None:
        if self._listeners_registered:
            return

        try:
            room = get_job_context().room
        except Exception as e:
            logger.warning("Cannot register video track listeners: %s", e)
            return

        self._listeners_registered = True

        @room.on("track_subscribed")
        def on_track_subscribed(
            track: rtc.Track,
            publication: rtc.RemoteTrackPublication,
            participant: rtc.RemoteParticipant,
        ) -> None:
            if track.kind != rtc.TrackKind.KIND_VIDEO:
                return

            self._create_video_stream(
                track=track,
                track_sid=publication.sid,
                participant_identity=participant.identity,
            )

        @room.on("track_unsubscribed")
        def on_track_unsubscribed(
            track: rtc.Track,
            publication: rtc.RemoteTrackPublication,
            participant: rtc.RemoteParticipant,
        ) -> None:
            if track.kind != rtc.TrackKind.KIND_VIDEO:
                return

            task = asyncio.create_task(
                self._aclose_video_stream(
                    track_sid=publication.sid,
                    participant_identity=participant.identity,
                )
            )
            self._video_tasks.add(task)

            def cleanup(done_task: asyncio.Task[None]) -> None:
                self._video_tasks.discard(done_task)
                try:
                    done_task.result()
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.warning(
                        "Video stream close task failed participant=%s track_sid=%s error=%s",
                        participant.identity,
                        publication.sid,
                        e,
                    )

            task.add_done_callback(cleanup)

    def _create_video_stream(
        self,
        *,
        track: rtc.Track,
        track_sid: str,
        participant_identity: str,
    ) -> None:
        if track_sid in self._video_streams:
            return

        video_stream = rtc.VideoStream(track)
        self._video_streams[track_sid] = video_stream

        async def read_stream() -> None:
            try:
                async for event in video_stream:
                    self._maybe_cache_video_frame(event.frame)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(
                    "Video stream reader failed participant=%s track_sid=%s error=%s",
                    participant_identity,
                    track_sid,
                    e,
                )
            finally:
                self._video_streams.pop(track_sid, None)

        task = asyncio.create_task(read_stream())
        self._video_tasks.add(task)

        def cleanup(done_task: asyncio.Task[None]) -> None:
            self._video_tasks.discard(done_task)

            try:
                done_task.result()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(
                    "Video stream task failed participant=%s track_sid=%s error=%s",
                    participant_identity,
                    track_sid,
                    e,
                )

        task.add_done_callback(cleanup)

        logger.info(
            "Attached video stream participant=%s track_sid=%s",
            participant_identity,
            track_sid,
        )

    def _maybe_cache_video_frame(self, frame: rtc.VideoFrame) -> None:
        vision_config = self.agent.avatar_config.vision_plugin_config

        if not vision_config.use_sampled_frame_input:
            return

        now = time.monotonic()
        interval = vision_config.vision_frame_sample_interval_sec

        if interval > 0 and now - self._last_video_frame_sample_ts < interval:
            return

        self._last_video_frame_sample_ts = now
        self._video_frame_buffer.append(frame)

    def _select_visual_frames_for_turn(self) -> list[rtc.VideoFrame]:
        vision_config = self.agent.avatar_config.vision_plugin_config

        if not vision_config.use_sampled_frame_input:
            return []

        if not self._video_frame_buffer:
            return []

        if vision_config.vision_input_mode == VisionInputMode.LATEST_FRAME_PER_TURN:
            return [self._video_frame_buffer[-1]]

        if vision_config.vision_input_mode == VisionInputMode.SAMPLED_FRAMES_PER_TURN:
            frame_count = min(
                vision_config.vision_frames_per_turn,
                len(self._video_frame_buffer),
            )
            return list(self._video_frame_buffer)[-frame_count:]

        return []

    def start(self) -> None:
        vision_config = self.agent.avatar_config.vision_plugin_config

        if not vision_config.use_sampled_frame_input:
            return

        self._try_attach_existing_video_tracks()
        self._register_video_track_listeners()

    async def _aclose_video_stream(
        self,
        *,
        track_sid: str,
        participant_identity: str,
    ) -> None:
        video_stream = self._video_streams.pop(track_sid, None)

        if video_stream is None:
            return

        try:
            await video_stream.aclose()
        except Exception as e:
            logger.warning(
                "Failed to close video stream participant=%s track_sid=%s error=%s",
                participant_identity,
                track_sid,
                e,
            )
            return

        logger.info(
            "Closed video stream participant=%s track_sid=%s",
            participant_identity,
            track_sid,
        )

    async def stop(self) -> None:
        streams = list(self._video_streams.items())
        self._video_streams.clear()

        for track_sid, video_stream in streams:
            try:
                await video_stream.aclose()
            except Exception as e:
                logger.warning(
                    "Failed to close video stream track_sid=%s error=%s",
                    track_sid,
                    e,
                )

        for task in list(self._video_tasks):
            task.cancel()

        if self._video_tasks:
            await asyncio.gather(*self._video_tasks, return_exceptions=True)
            self._video_tasks.clear()

        self._video_frame_buffer.clear()

    def _build_visual_instruction(self, frame_count: int) -> str:
        if frame_count == 1:
            frame_desc = "One sampled moment"
            visual_scope = "the video"
        else:
            frame_desc = f"{frame_count} sampled moments, ordered from earliest to latest,"
            visual_scope = "the video sequence"

        return (
            f"\n{VISUAL_INPUT_PREFIX}\n"
            f"{frame_desc} from the user's live video stream are available for this user message. "
            "Always answer the user's text message normally. "
            "Use the live video context only when the user's message explicitly refers to the video, camera, screen, scene, visible object, gesture, appearance, action, or something currently shown, "
            "or when the user's question clearly depends on what is visible. "
            "If the user's message does not require visual grounding, ignore the live video context and respond as a normal conversation. "
            f"When visual grounding is needed, rely only on what is visible in {visual_scope} and avoid guessing beyond what is shown. "
            "When responding naturally to the user, prefer phrasing such as "
            "'from your video', 'based on your video', or 'from what I can see in the video', "
            "and avoid phrasing such as 'from the attached frames', 'in the attached frames', 'from the image', or 'from the picture' "
            "unless the user explicitly asks about frames or images."
        )

    def _message_has_visual_input(self, message: llm.ChatMessage) -> bool:
        content = getattr(message, "content", None)

        if not isinstance(content, list):
            return False

        for part in content:
            if isinstance(part, str):
                stripped = part.strip()
                if VISUAL_INPUT_PREFIX in stripped:
                    return True
                if stripped.startswith(VIDEO_FRAME_LABEL_PREFIX):
                    return True
                if stripped == LATEST_VIDEO_FRAME_LABEL:
                    return True

            if getattr(part, "type", None) == "image_content":
                return True

            if part.__class__.__name__ == "ImageContent":
                return True

        return False

    def inject_into_chat_ctx(self, chat_ctx: llm.ChatContext) -> None:
        vision_config = self.agent.avatar_config.vision_plugin_config
        frames = self._select_visual_frames_for_turn()

        if not frames:
            return

        latest_user_message: llm.ChatMessage | None = None

        for item in reversed(chat_ctx.items):
            if isinstance(item, llm.ChatMessage) and item.role == "user":
                latest_user_message = item
                break

        if latest_user_message is None:
            logger.warning("No latest user message found; skip visual frame injection")
            return

        # Ensure content is appendable.
        if latest_user_message.content is None:
            latest_user_message.content = []
        elif not isinstance(latest_user_message.content, list):
            latest_user_message.content = [latest_user_message.content]

        # Avoid duplicate visual injection.
        if self._message_has_visual_input(latest_user_message):
            logger.debug("Latest user message already has visual input; skip duplicate injection")
            return

        frame_count = len(frames)

        latest_user_message.content.append(self._build_visual_instruction(frame_count))

        for idx, frame in enumerate(frames, start=1):
            if frame_count > 1:
                latest_user_message.content.append(
                    f"{VIDEO_FRAME_LABEL_PREFIX}{idx}/{frame_count} — chronological order]"
                )
            else:
                latest_user_message.content.append(LATEST_VIDEO_FRAME_LABEL)

            latest_user_message.content.append(
                llm.ImageContent(
                    image=frame,
                    inference_width=vision_config.vision_inference_width,
                    inference_height=vision_config.vision_inference_height,
                )
            )

        logger.info(
            "Injected visual frames into latest user message frame_count=%s mode=%s",
            frame_count,
            vision_config.vision_input_mode,
        )

        if vision_config.vision_clear_after_turn:
            self._video_frame_buffer.clear()
