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
import math
import time
from dataclasses import dataclass

import aiohttp
from livekit import api
from livekit.protocol import agent, models

from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.host.execution.manager import ExecutionManager
from alphaavatar.host.execution.schemas import ExecutionReservation, ExecutionView
from alphaavatar.host.sessions.schemas import SessionRequest
from alphaavatar.host.version import __version__

from .config import LiveKitConfig, LiveKitCredentials, websocket_url

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _Offer:
    reservation: ExecutionReservation
    epoch: int
    identity: str
    fingerprint: tuple
    room_name: str
    participant_identity: str | None


def _fingerprint(job: agent.Job) -> tuple:
    # Counts, timestamps, participant metadata and JobState may change before assignment.
    return (
        job.id,
        job.dispatch_id,
        job.type,
        job.room.sid,
        job.room.name,
        job.agent_name,
        job.participant.sid if job.HasField("participant") else None,
        job.participant.identity if job.HasField("participant") else None,
    )


class LiveKitDispatch:
    """Native control adapter; a new registration never claims ownership of old jobs."""

    def __init__(
        self,
        config: LiveKitConfig,
        credentials: LiveKitCredentials,
        manager: ExecutionManager,
        *,
        agent_name: str,
    ) -> None:
        self._config, self._credentials, self._manager = config, credentials, manager
        self._agent_name = agent_name

        self._offers: dict[str, _Offer] = {}
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._epoch = 0
        self._registered = False
        self._accepting = True
        self._closed = asyncio.Event()
        self._send_lock, self._status_lock = asyncio.Lock(), asyncio.Lock()
        self._last_sent: dict[str, tuple[int, str]] = {}
        self._assigned_jobs: dict[str, ExecutionReservation] = {}
        self._last_pong = 0.0
        self._run_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self.worker_id = ""

    @property
    def ready(self) -> bool:
        return self._registered and self._accepting and not self._closed.is_set()

    @staticmethod
    def _status(view: ExecutionView) -> tuple[int, str]:
        if view.state in ("reserved", "starting"):
            return agent.JobStatus.JS_PENDING, ""
        if view.state in ("running", "stopping"):
            return agent.JobStatus.JS_RUNNING, ""
        if view.state == "success":
            return agent.JobStatus.JS_SUCCESS, ""
        return agent.JobStatus.JS_FAILED, view.reason or "execution_failed"

    async def _send(
        self, ws: aiohttp.ClientWebSocketResponse, message: agent.WorkerMessage
    ) -> None:
        async with asyncio.timeout(self._config.registration_timeout):
            async with self._send_lock:
                if ws is not self._ws or ws.closed:
                    raise ConnectionError("LiveKit control connection changed")
                await ws.send_bytes(message.SerializeToString())

    def _release_offers(self, reason: str) -> None:
        for offer in self._offers.values():
            self._manager.cancel_reservation(offer.reservation, reason)
        self._offers.clear()

    async def _availability(
        self, ws: aiohttp.ClientWebSocketResponse, request: agent.AvailabilityRequest, epoch: int
    ) -> None:
        if epoch != self._epoch or ws is not self._ws:
            return
        job = request.job
        offer = self._offers.get(job.id)
        allowed = (
            self.ready
            and ws is self._ws
            and epoch == self._epoch
            and not request.resuming
            and job.type == agent.JobType.JT_ROOM
            and bool(job.id)
            and bool(job.room.name)
            and job.agent_name in ("", self._agent_name)
        )
        if offer is not None and (offer.epoch != epoch or offer.fingerprint != _fingerprint(job)):
            self._manager.cancel_reservation(offer.reservation, "availability_identity_changed")
            self._offers.pop(job.id, None)
            offer, allowed = None, False
        if allowed and offer is None:
            reservation = self._manager.reserve(backend="livekit", source_id=job.id)
            if reservation is not None:
                offer = _Offer(
                    reservation=reservation,
                    epoch=epoch,
                    identity=f"alphaavatar-{reservation.execution_id}",
                    fingerprint=_fingerprint(job),
                    room_name=job.room.name,
                    participant_identity=(job.participant.identity or None)
                    if job.HasField("participant")
                    else self._config.participant_identity,
                )
                self._offers[job.id] = offer
        available = bool(
            allowed and offer is not None and self._manager.reservation_valid(offer.reservation)
        )
        response = agent.AvailabilityResponse(
            job_id=job.id,
            available=available,
            supports_resume=False,
            participant_identity=offer.identity if available else "",
            participant_name=self._agent_name if available else "",
        )
        await self._send(ws, agent.WorkerMessage(availability=response))

    def _assignment(self, assignment: agent.JobAssignment, epoch: int) -> None:
        if epoch != self._epoch or not self._registered:
            return
        offer = self._offers.pop(assignment.job.id, None)
        if offer is None:
            # Duplicate, unsolicited or late assignments never allocate another execution.
            return
        if (
            not self._accepting
            or offer.epoch != epoch
            or offer.fingerprint != _fingerprint(assignment.job)
            or not assignment.token
        ):
            self._manager.cancel_reservation(offer.reservation, "assignment_identity_mismatch")
            return
        # Wire ownership belongs to this registration only, not the Host's full ledger.
        self._assigned_jobs[assignment.job.id] = offer.reservation
        try:
            url = websocket_url(assignment.url or self._credentials.url)
            request = SessionRequest(
                attachment_id=offer.reservation.attachment_id,
                backend="livekit",
                source_id=assignment.job.id,
                connection={
                    "url": url,
                    "token": assignment.token,
                    "room_name": offer.room_name,
                    "agent_identity": offer.identity,
                    "participant_identity": offer.participant_identity,
                },
            )
        except ValueError:
            self._manager.cancel_reservation(offer.reservation, "invalid_assignment")
            return
        if not self._manager.assign(offer.reservation, request):
            self._manager.cancel_reservation(offer.reservation, "assignment_not_admitted")

    def _termination(self, job_id: str, epoch: int) -> None:
        if epoch != self._epoch or not self._registered:
            return
        offer = self._offers.pop(job_id, None)
        reservation = offer.reservation if offer is not None else self._assigned_jobs.get(job_id)
        if reservation is not None:
            self._manager.request_stop(
                backend=reservation.backend,
                source_id=reservation.source_id,
                reason="dispatch_termination",
                reservation=reservation,
            )

    async def _sync_status(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        async with self._status_lock:
            if not self._registered or ws is not self._ws:
                return
            views = tuple(
                view
                for view in self._manager.snapshot()
                if view.backend == "livekit"
                and (reservation := self._assigned_jobs.get(view.source_id)) is not None
                and view.execution_id == reservation.execution_id
            )
            for view in views:
                status = self._status(view)
                if self._last_sent.get(view.source_id) != status:
                    await self._send(
                        ws,
                        agent.WorkerMessage(
                            update_job=agent.UpdateJobStatus(
                                job_id=view.source_id, status=status[0], error=status[1]
                            )
                        ),
                    )
                    self._last_sent[view.source_id] = status
            available = self.ready and self._manager.available
            await self._send(
                ws,
                agent.WorkerMessage(
                    update_worker=agent.UpdateWorkerStatus(
                        status=agent.WorkerStatus.WS_AVAILABLE
                        if available
                        else agent.WorkerStatus.WS_FULL,
                        load=self._manager.load if self.ready else 1.0,
                        job_count=sum(
                            view.state in ("starting", "running", "stopping") for view in views
                        ),
                    )
                ),
            )
            now = time.monotonic()
            for job_id, offer in tuple(self._offers.items()):
                if offer.reservation.expires_at <= now:
                    self._offers.pop(job_id, None)

    async def _receive(self, ws: aiohttp.ClientWebSocketResponse, epoch: int) -> None:
        while epoch == self._epoch and not self._closed.is_set():
            frame = await ws.receive()
            if frame.type != aiohttp.WSMsgType.BINARY:
                raise ConnectionError("LiveKit control channel did not return a binary message")
            if epoch != self._epoch or ws is not self._ws:
                return

            message = agent.ServerMessage()
            message.ParseFromString(frame.data)
            which = message.WhichOneof("message")
            if which == "availability":
                await self._availability(ws, message.availability, epoch)
            elif which == "assignment":
                self._assignment(message.assignment, epoch)
            elif which == "termination":
                self._termination(message.termination.job_id, epoch)
            elif which == "pong":
                self._last_pong = time.monotonic()
            elif which == "go_away":
                raise ConnectionError("LiveKit requested control reconnection")
            elif which == "register":
                raise ValueError("Unexpected duplicate LiveKit registration")

    async def _report(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        while not self._closed.is_set():
            self._manager.changed.clear()
            await self._sync_status(ws)
            try:
                async with asyncio.timeout(self._config.status_interval):
                    await self._manager.changed.wait()
            except TimeoutError:
                pass

    async def _ping(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        while not self._closed.is_set():
            if time.monotonic() - self._last_pong > self._config.pong_timeout:
                raise TimeoutError("LiveKit control pong timed out")
            await self._send(
                ws, agent.WorkerMessage(ping=agent.WorkerPing(timestamp=int(time.time() * 1000)))
            )
            await asyncio.sleep(self._config.ping_interval)

    async def _connected(self, ws: aiohttp.ClientWebSocketResponse, epoch: int) -> None:
        tasks = [
            asyncio.create_task(self._receive(ws, epoch), name="livekit_dispatch_receive"),
            asyncio.create_task(self._report(ws), name="livekit_dispatch_status"),
            asyncio.create_task(self._ping(ws), name="livekit_dispatch_ping"),
        ]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task.cancelled():
                    raise RuntimeError("LiveKit control task cancelled unexpectedly")
                await task

            if not self._closed.is_set():
                raise ConnectionError("LiveKit control task ended unexpectedly")
        finally:
            # Fence readiness before awaiting task cancellation or execution cleanup.
            self._registered = False
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _retire_control(self) -> None:
        self._registered = False
        self._release_offers("control_connection_changed")
        assigned = tuple(self._assigned_jobs.values())
        self._assigned_jobs.clear()
        self._last_sent.clear()
        ws, self._ws = self._ws, None
        if assigned and not self._closed.is_set():
            logger.warning(
                "LiveKit control retired epoch=%d assigned_jobs=%d policy=finish_execution",
                self._epoch,
                len(assigned),
            )
        try:
            # The Host owns stopping and reaping. No migration acknowledgement is assumed.
            await self._manager.control_lost(assigned, reason="dispatch_control_lost")
        finally:
            if ws is not None:
                async with asyncio.timeout(self._config.registration_timeout):
                    await ws.close()

    async def _run(self) -> None:
        retries = 0
        timeout = aiohttp.ClientTimeout(total=None, connect=self._config.registration_timeout)
        async with aiohttp.ClientSession(timeout=timeout) as client:
            while not self._closed.is_set():
                self._epoch += 1
                epoch, stable_since = self._epoch, None
                try:
                    token = (
                        api.AccessToken(self._credentials.api_key, self._credentials.api_secret)
                        .with_grants(api.VideoGrants(agent=True))
                        .to_jwt()
                    )
                    async with asyncio.timeout(self._config.registration_timeout):
                        self._ws = await client.ws_connect(
                            self._credentials.url.rstrip("/") + "/agent",
                            headers={"Authorization": f"Bearer {token}"},
                            max_msg_size=self._config.max_message_bytes,
                            autoping=True,
                        )
                        register = agent.RegisterWorkerRequest(
                            type=agent.JobType.JT_ROOM,
                            agent_name=self._agent_name,
                            version=__version__,
                            ping_interval=math.ceil(self._config.ping_interval),
                            allowed_permissions=models.ParticipantPermission(
                                can_publish=True,
                                can_subscribe=True,
                                can_publish_data=True,
                                agent=True,
                            ),
                        )
                        await self._send(self._ws, agent.WorkerMessage(register=register))
                        first = agent.ServerMessage()
                        first.ParseFromString(await self._ws.receive_bytes())
                        if (
                            first.WhichOneof("message") != "register"
                            or not first.register.worker_id
                        ):
                            raise ValueError("LiveKit did not acknowledge worker registration")

                    self.worker_id = first.register.worker_id
                    self._registered = True
                    stable_since = self._last_pong = time.monotonic()
                    logger.info(
                        "LiveKit control registered worker_id=%s epoch=%d", self.worker_id, epoch
                    )
                    await self._connected(self._ws, epoch)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    if self._closed.is_set():
                        return
                    if (
                        stable_since is not None
                        and time.monotonic() - stable_since >= self._config.pong_timeout
                    ):
                        retries = 0
                    if retries >= self._config.reconnect_attempts:
                        raise RuntimeError("LiveKit control reconnect budget exhausted") from None
                    retries += 1
                    logger.warning(
                        "LiveKit control reconnect attempt=%d error_type=%s",
                        retries,
                        type(error).__name__,
                    )
                finally:
                    self._registered = False
                    await wait_for_cleanup(
                        asyncio.create_task(self._retire_control(), name="livekit_control_retire")
                    )
                try:
                    async with asyncio.timeout(min(2 ** min(retries - 1, 4), 10)):
                        await self._closed.wait()
                except TimeoutError:
                    pass

    async def run(self) -> None:
        if self._run_task is not None or self._close_task is not None:
            raise RuntimeError("LiveKit dispatch can only run once")

        self._run_task = asyncio.create_task(self._run(), name="livekit_dispatch")
        self._run_task.add_done_callback(
            lambda task: None if task.cancelled() else task.exception()
        )
        await asyncio.shield(self._run_task)

    async def stop_accepting(self) -> None:
        self._accepting = False
        self._release_offers("host_draining")
        self._manager.changed.set()
        if self._registered and self._ws is not None:
            try:
                async with asyncio.timeout(self._config.registration_timeout):
                    await self._sync_status(self._ws)
            except (OSError, TimeoutError, aiohttp.ClientError):
                pass

    async def _close(self) -> None:
        try:
            await self.stop_accepting()
        finally:
            self._closed.set()
            if self._run_task is not None:
                if not self._run_task.done():
                    self._run_task.cancel()
                await asyncio.gather(self._run_task, return_exceptions=True)
            self._registered = False

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="livekit_dispatch_close")
            self._close_task.add_done_callback(
                lambda task: None if task.cancelled() else task.exception()
            )
        await wait_for_cleanup(self._close_task)
