# Copyright 2025 AlphaAvatar project
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
# airi_avatar/worker.py
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import numpy as np
from livekit import rtc
from livekit.agents import (
    NOT_GIVEN,
    AgentSession,
    NotGivenOr,
)
from livekit.agents.voice.avatar import (
    AudioSegmentEnd,
    AvatarOptions,
    AvatarRunner,
    QueueAudioOutput,
    VideoGenerator,
)

from alphaavatar.agents.sessions import VirtialCharacterSession

from .config import AiriConfig

_AVATAR_IDENTITY = "airi-avatar-worker"


class AiriCharacterSession(VirtialCharacterSession):
    def __init__(self, avatar_config: AiriConfig):
        self._avatar_config = avatar_config
        self._avatar_participant_identity = _AVATAR_IDENTITY

    async def start(
        self,
        agent_identity: str,
        agent_session: AgentSession,
        room: rtc.Room,
        *,
        livekit_url: NotGivenOr[str] = NOT_GIVEN,
        livekit_api_key: NotGivenOr[str] = NOT_GIVEN,
        livekit_api_secret: NotGivenOr[str] = NOT_GIVEN,
    ) -> None:
        attrs = dict(room.local_participant.attributes)
        attrs["lk.publish_on_behalf"] = agent_identity
        await room.local_participant.set_attributes(attrs)

        audio_buffer = QueueAudioOutput(sample_rate=self._avatar_config.audio_sample_rate)
        agent_session.output.audio = audio_buffer

        options = AvatarOptions(
            video_width=self._avatar_config.video_width,
            video_height=self._avatar_config.video_height,
            video_fps=self._avatar_config.video_fps,
            audio_sample_rate=self._avatar_config.audio_sample_rate,
            audio_channels=self._avatar_config.audio_channels,
        )

        video_gen = AiriVideoGenerator(room=room, config=self._avatar_config)
        runner = AvatarRunner(
            room=room,
            audio_recv=audio_buffer,
            video_gen=video_gen,
            options=options,
        )

        async def _run_runner():
            await runner.start()
            try:
                await runner.wait_for_complete()
            finally:
                await runner.aclose()
                await video_gen.aclose()

        asyncio.create_task(_run_runner())


class AiriVideoGenerator(VideoGenerator):
    """
    The LiveKit AvatarRunner's abstract VideoGenerator interface is encapsulated into a layer to interface with AIRI's rendering logic.

    (Placeholder for now: When actually integrating AIRI, you only need to push the audio frame to AIRI within these methods, then capture frames from AIRI and generate the LiveKit VideoFrame.)
    """

    def __init__(self, room: rtc.Room, config: AiriConfig) -> None:
        self._room = room
        self._config = config
        self._audio_queue: asyncio.Queue[rtc.AudioFrame | AudioSegmentEnd] = asyncio.Queue()
        self._running = True

        # TODO: Initialize the AIRI connection/context here, for example:
        # - Start an AIRI instance
        # - Tell AIRI via websocket/HTTP, "I will feed you an audio file, and you give me a live2d animation stream."
        # - Save necessary handlers

    async def push_audio(self, frame: rtc.AudioFrame | AudioSegmentEnd) -> None:
        """
        This is called every time an audio frame is received by AvatarRunner.
        You either need to hand it over to AIRI, or put it in a queue for background consumption.
        """
        # Step 1: First, add the items to the queue to ensure there is no blocking.
        await self._audio_queue.put(frame)

        # Step 2: TODO - Pass the frame to AIRI:
        # - If you are running AIRI in the same process: directly call AIRI's interface
        # - If it's a separate stage-web: you can push the audio via WebSocket/HTTP
        # - Note that you need to convert rtc.AudioFrame.data to PCM16 / float32, and the sample rate is config.audio_sample_rate

    def clear_buffer(self):
        """
        Used to interrupt the current playback (e.g., when a user interrupts the agent's speech).
        Here you need to notify AIRI to stop the current lip-sync/animation.
        """
        # Clear the queue
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
                self._audio_queue.task_done()
            except asyncio.QueueEmpty:
                break

        # TODO: Notify AIRI to immediately stop the current animation (e.g., reset to idle pose).

    async def _fake_frame_loop(
        self,
    ) -> AsyncIterator[rtc.VideoFrame | rtc.AudioFrame | AudioSegmentEnd]:
        """
        Placeholder implementation: Continuously generate a pure black screen.
        Before you actually integrate with AIRI, you can use this to test whether
        the entire AvatarRunner/DataStream pipeline is working correctly.
        """
        width = self._config.video_width
        height = self._config.video_height
        fps = self._config.video_fps
        frame_interval = 1.0 / fps

        rgba = np.zeros((height, width, 4), dtype=np.uint8)
        rgba[..., 0] = 255  # R = 255
        rgba[..., 1] = 0  # G = 0
        rgba[..., 2] = 0  # B = 0
        rgba[..., 3] = 255

        while self._running:
            frame_bytes = rgba.tobytes()

            frame = rtc.VideoFrame(
                width,
                height,
                rtc.VideoBufferType.RGBA,
                frame_bytes,
            )

            yield frame
            await asyncio.sleep(frame_interval)

    async def __aiter__(self) -> AsyncIterator[rtc.VideoFrame | rtc.AudioFrame | AudioSegmentEnd]:
        """
        AvatarRunner iterates over this generator in a loop,
        and you continuously generate VideoFrame / AudioFrame / AudioSegmentEnd.
        """
        async for frame in self._fake_frame_loop():
            yield frame

    async def aclose(self) -> None:
        """
        Clean up resources when closing.
        """
        self._running = False
        # TODO: Disable AIRI connection if necessary.
