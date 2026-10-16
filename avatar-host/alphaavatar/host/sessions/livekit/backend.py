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
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING
from uuid import uuid4

from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.lifecycle import LifecycleComponent
from alphaavatar.host.sessions.attachment import SessionAttachment
from alphaavatar.host.sessions.base import SessionBackend, SessionConnection
from alphaavatar.host.sessions.mode import resolve_session_mode, resolve_session_type
from alphaavatar.host.sessions.schemas import SessionRequest

from .config import LiveKitConfig, LiveKitCredentials
from .connection import LiveKitConnection

if TYPE_CHECKING:
    from alphaavatar.host.configs.application import ApplicationConfig
    from alphaavatar.host.execution.execution import HostExecution
    from alphaavatar.host.execution.manager import ExecutionManager

    from .dispatch import LiveKitDispatch


class LiveKitBackend(SessionBackend):
    def __init__(self, config: LiveKitConfig) -> None:
        self._config = config

        self._credentials = LiveKitCredentials.from_env()
        self._dispatch: LiveKitDispatch | None = None
        self._manager: ExecutionManager | None = None
        self._closed = False

    @property
    def ready(self) -> bool:
        if self._closed:
            return False
        if self._dispatch is not None:
            return self._dispatch.ready

        return self._manager is not None and any(
            item.state == "running" for item in self._manager.snapshot()
        )

    def connection(self, request: SessionRequest) -> SessionConnection:
        if self._closed:
            raise RuntimeError("LiveKit backend is closing or closed")

        if request.backend != "livekit":
            raise ValueError("Session request selected a different backend")

        return LiveKitConnection(request, self._config)

    async def serve(self, manager: ExecutionManager, *, agent_name: str) -> None:
        if self._closed or self._manager is not None:
            raise RuntimeError("LiveKit backend can only serve once")

        self._manager = manager
        credentials = self._credentials
        if self._config.connection_mode == "dispatch":
            from .dispatch import LiveKitDispatch

            self._dispatch = LiveKitDispatch(
                self._config, credentials, manager, agent_name=agent_name
            )
            await self._dispatch.run()
            return

        from livekit import api

        source_id = uuid4().hex
        reservation = manager.reserve(backend="livekit", source_id=source_id)
        if reservation is None:
            raise RuntimeError("Direct execution was not admitted")

        agent_identity = f"alphaavatar-{reservation.execution_id}"
        token = (
            api.AccessToken(credentials.api_key, credentials.api_secret)
            .with_identity(agent_identity)
            .with_name(agent_name)
            .with_kind("agent")
            .with_grants(api.VideoGrants(room_join=True, room=self._config.room_name, agent=True))
            .to_jwt()
        )
        request = SessionRequest(
            attachment_id=reservation.attachment_id,
            backend="livekit",
            source_id=source_id,
            connection={
                "url": credentials.url,
                "token": token,
                "room_name": self._config.room_name,
                "agent_identity": agent_identity,
                "participant_identity": self._config.participant_identity,
            },
        )
        if not manager.assign(reservation, request):
            raise RuntimeError("Direct execution reservation expired")

        result = await manager.wait(reservation)
        if result.outcome != "success":
            raise RuntimeError(f"Direct execution ended: {result.reason}")

    async def stop_accepting(self) -> None:
        self._closed = True
        if self._dispatch is not None:
            await self._dispatch.stop_accepting()

    async def aclose(self) -> None:
        self._closed = True
        if self._dispatch is not None:
            await self._dispatch.aclose()

    async def attachment(
        self,
        *,
        connection: SessionConnection,
        execution: HostExecution,
        config: ApplicationConfig,
    ) -> SessionAttachment:
        if self._closed:
            raise RuntimeError("LiveKit backend is closing or closed")

        from alphaavatar.rtc.livekit.audio.input import LiveKitAudioInput
        from alphaavatar.rtc.livekit.audio.output import LiveKitTransientAudioOutput
        from alphaavatar.rtc.livekit.status.output import LiveKitStatusOutput
        from alphaavatar.rtc.livekit.text import LiveKitTextInput
        from alphaavatar.rtc.livekit.transcript.output import LiveKitTranscriptOutput
        from alphaavatar.rtc.livekit.video.input import LiveKitVideoInput

        from .character import LiveKitCharacterTransport

        if not isinstance(connection, LiveKitConnection):
            raise TypeError("LiveKit requires a LiveKit connection")

        access, avatar = connection.context, config.avatar
        runtime, engine, room = execution.runtime, execution.engine, connection.room
        mode = resolve_session_mode(resolve_session_type(access.metadata))
        resources = AsyncExitStack()

        def own(component: LifecycleComponent) -> LifecycleComponent:
            resources.push_async_callback(component.on_stop)
            return component

        try:
            tts = runtime.foundation.voice.tts
            if mode.audio_output_enabled and tts is None:
                raise ValueError(
                    "The selected session requires audio output but no TTS is configured"
                )

            character = None
            excluded: frozenset[str] = frozenset()
            if avatar.character.plugin is not None:
                transport = LiveKitCharacterTransport(
                    room=room,
                    agent_identity=access.agent_identity,
                    livekit_url=connection.url,
                )

                # Until the Character factory accepts the transport, this local stack owns it.
                transport_owner = AsyncExitStack()
                transport_owner.push_async_callback(transport.on_stop)
                try:
                    character = avatar.character.get_plugin(runtime, transport=transport)
                    if character is None:
                        raise RuntimeError("Enabled Character factory returned no session")
                except BaseException:
                    await wait_for_cleanup(asyncio.create_task(transport_owner.aclose()))
                    raise

                transport_owner.pop_all()
                own(character)
                excluded = frozenset((transport.participant_identity,))

            outputs = [
                own(
                    LiveKitStatusOutput(
                        room=room,
                        output_runtime=runtime.output,
                        action_topic=avatar.status.action_topic,
                    )
                )
            ]
            audio_output = None
            if mode.audio_output_enabled:
                assert tts is not None
                audio_output = own(
                    LiveKitTransientAudioOutput(
                        room=room,
                        output_runtime=runtime.output,
                        sample_rate=tts.sample_rate,
                        num_channels=tts.num_channels,
                        subscription_name=f"livekit:audio:{connection.request.attachment_id}",
                    )
                )
                outputs.append(audio_output)

            if mode.text_output_enabled:
                outputs.append(
                    own(
                        LiveKitTranscriptOutput(
                            room=room,
                            output_runtime=runtime.output,
                            track_sid=(lambda: audio_output.track_sid)
                            if audio_output is not None
                            else None,
                        )
                    )
                )

            inputs = []
            if mode.audio_input_enabled:
                inputs.append(
                    own(
                        LiveKitAudioInput(
                            room=room,
                            perception=runtime.perception,
                            sample_rate=16000,
                            num_channels=1,
                            frame_size_ms=avatar.runtime.perception.audio_frame_size_ms,
                            excluded_participant_identities=excluded,
                        )
                    )
                )
            if mode.video_input_enabled and avatar.vision.enabled:
                inputs.append(
                    own(
                        LiveKitVideoInput(
                            room=room,
                            perception=runtime.perception,
                            publish_interval_sec=avatar.runtime.perception.video_publish_interval_sec,
                            excluded_participant_identities=excluded,
                        )
                    )
                )

            text_input = None
            if mode.text_input_enabled:
                text_input = own(
                    LiveKitTextInput(
                        room=room,
                        clock=runtime.perception.clock,
                        session_id=runtime.session.session_id,
                        participant_identities=frozenset((access.participant_identity,)),
                        submit=engine.submit_input,
                        max_streams=avatar.runtime.engine.max_pending_admissions,
                        max_bytes=avatar.runtime.engine.max_input_bytes,
                    )
                )
                inputs.append(text_input)

            async def abort_ingress() -> None:
                if text_input is not None and text_input.has_pending_streams:
                    await connection.disconnect()

            monitors = []
            if text_input is not None:
                monitors.append(text_input.wait_failed)
            if character is not None:
                monitors.append(character.wait_failed)

            attachment = SessionAttachment(
                attachment_id=connection.request.attachment_id,
                connection=connection,
                inputs=inputs,
                outputs=outputs,
                presentations=(character,) if character is not None else (),
                failure_monitors=monitors,
                abort_ingress=abort_ingress,
            )
            resources.pop_all()
            return attachment
        except BaseException as original:
            try:
                await wait_for_cleanup(
                    asyncio.create_task(resources.aclose(), name="session_assembly_rollback")
                )
            except BaseException as cleanup:
                raise original from cleanup
            raise
