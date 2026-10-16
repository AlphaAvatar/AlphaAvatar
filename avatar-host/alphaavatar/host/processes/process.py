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
import secrets
import sys
from typing import Any

from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.core.lifecycle import LifecycleComponent
from alphaavatar.host.sessions.schemas import SessionRequest

from .channel import receive, send
from .config import ProcessConfig
from .schemas import (
    MAX_LAUNCH_BYTES,
    MAX_MESSAGE_BYTES,
    ProcessLaunch,
    ProcessMessage,
    ProcessResult,
)


class ExecutionProcess(LifecycleComponent):
    """Own one Python child and its authenticated control channel; never respawn it."""

    def __init__(
        self,
        *,
        execution_id: str,
        application: str,
        request: SessionRequest,
        config: ProcessConfig,
        devmode: bool = False,
    ) -> None:
        self.execution_id, self._application = execution_id, application
        self._request: SessionRequest | None = request.model_copy(deep=True)
        self._config, self._devmode = config, devmode

        self._ticket = secrets.token_hex(32)
        self._server: asyncio.Server | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._spawn_task: asyncio.Task[asyncio.subprocess.Process] | None = None
        self._start_task: asyncio.Task[None] | None = None
        self._read_task: asyncio.Task[None] | None = None
        self._result_task: asyncio.Task[ProcessResult] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._accept_tasks: set[asyncio.Task[None]] = set()
        self._spawned, self._connected, self._ready = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )
        self._terminal: ProcessMessage | None = None
        self._protocol_failed = self._forced = False
        self._reason = ""

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    @property
    def reaped(self) -> bool:
        if self._spawn_task is not None and not self._spawn_task.done():
            return False
        process = self._process
        if process is None and self._spawn_task is not None and not self._spawn_task.cancelled():
            try:
                process = self._spawn_task.result()
            except Exception:
                return True
        return process is None or process.returncode is not None

    @staticmethod
    def _observe(task: asyncio.Future[Any]) -> None:
        if not task.cancelled():
            task.exception()

    def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self._close_task is not None or len(self._accept_tasks) >= 4:
            writer.close()
            return

        task = asyncio.create_task(self._authenticate(reader, writer), name="execution_ipc_auth")
        self._accept_tasks.add(task)
        task.add_done_callback(self._accept_tasks.discard)
        task.add_done_callback(self._observe)

    async def _authenticate(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        accepted = False
        try:
            async with asyncio.timeout(self._config.ipc_timeout):
                hello = await receive(reader)
                await self._spawned.wait()
                if (
                    self._close_task is not None
                    or self._connected.is_set()
                    or hello.kind != "hello"
                    or hello.execution_id != self.execution_id
                    or hello.pid != self.pid
                    or hello.outcome
                    or hello.reason
                    or hello.stop_reason
                    or not secrets.compare_digest(hello.ticket, self._ticket)
                ):
                    return
                self._reader, self._writer = reader, writer
                accepted = True
                self._connected.set()
        except (TimeoutError, EOFError, ValueError, OSError):
            return
        finally:
            if not accepted:
                writer.close()
                try:
                    async with asyncio.timeout(self._config.ipc_timeout):
                        await writer.wait_closed()
                except (TimeoutError, OSError):
                    pass

    async def _read_messages(self) -> None:
        assert self._reader is not None
        try:
            while True:
                message = await receive(self._reader)
                if message.execution_id != self.execution_id or message.ticket or message.pid:
                    raise ValueError("Execution control identity changed")

                if (
                    message.kind == "ready"
                    and not self._ready.is_set()
                    and not message.outcome
                    and not message.reason
                    and not message.stop_reason
                ):
                    self._ready.set()
                elif message.kind == "result" and message.outcome:
                    if message.outcome == "success" and not self._ready.is_set():
                        raise ValueError("Execution reported success before readiness")
                    self._terminal = message
                    return
                else:
                    raise ValueError("Unexpected execution control message")
        except (EOFError, ValueError, OSError):
            self._protocol_failed = True
        finally:
            self._ready.set()

    async def _start(self) -> None:
        async with asyncio.timeout(self._config.startup_timeout):
            self._server = await asyncio.start_server(
                self._accept, "127.0.0.1", 0, limit=MAX_MESSAGE_BYTES
            )
            port = self._server.sockets[0].getsockname()[1]
            assert self._request is not None
            launch = (
                ProcessLaunch(
                    execution_id=self.execution_id,
                    port=port,
                    ticket=self._ticket,
                    application=self._application,
                    request=self._request,
                    log_level="DEBUG" if self._devmode else "INFO",
                    ipc_timeout=self._config.ipc_timeout,
                )
                .model_dump_json()
                .encode("utf-8")
                + b"\n"
            )
            if len(launch) > MAX_LAUNCH_BYTES:
                raise ValueError("Execution launch configuration is too large")

            # Shield OS creation so cancellation cannot lose an already-created child.
            self._spawn_task = asyncio.create_task(
                asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "alphaavatar.host.processes.entrypoint",
                    stdin=asyncio.subprocess.PIPE,
                ),
                name=f"execution_spawn:{self.execution_id}",
            )
            self._spawn_task.add_done_callback(self._observe)
            self._process = await asyncio.shield(self._spawn_task)
            self._spawned.set()
            assert self._process.stdin is not None
            self._process.stdin.write(launch)
            async with asyncio.timeout(self._config.ipc_timeout):
                await self._process.stdin.drain()

            self._process.stdin.close()
            self._application = ""
            self._request = None

            connected = asyncio.create_task(self._connected.wait())
            exited = asyncio.create_task(self._process.wait())
            try:
                done, _ = await asyncio.wait(
                    (connected, exited), return_when=asyncio.FIRST_COMPLETED
                )
                if exited in done:
                    raise RuntimeError("Execution exited before IPC authentication")
            finally:
                for task in (connected, exited):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(connected, exited, return_exceptions=True)

            # wait_closed also waits for accepted transports on supported Python versions.
            # Stop accepting now; the live IPC connection is closed during owner shutdown.
            self._server.close()
            self._read_task = asyncio.create_task(
                self._read_messages(), name="execution_ipc_receive"
            )
            self._read_task.add_done_callback(self._observe)
            self._result_task = asyncio.create_task(self._result(), name="execution_process_result")
            self._result_task.add_done_callback(self._observe)
            await self._ready.wait()
            if self._protocol_failed or self._terminal is not None or self._close_task is not None:
                raise RuntimeError("Execution did not become ready")

    async def on_start(self) -> None:
        if self._close_task is not None:
            raise RuntimeError("Execution process is closing or closed")
        if self._start_task is None:
            self._start_task = asyncio.create_task(self._start(), name="execution_process_start")
            self._start_task.add_done_callback(self._observe)
        try:
            await asyncio.shield(self._start_task)
        except BaseException as original:
            try:
                await self.on_stop()
            except BaseException as cleanup:
                raise original from cleanup
            raise

    async def _result(self) -> ProcessResult:
        assert self._process is not None and self._read_task is not None
        exited = asyncio.create_task(self._process.wait())
        try:
            done, _ = await asyncio.wait(
                (self._read_task, exited), return_when=asyncio.FIRST_COMPLETED
            )
            if self._read_task in done and not exited.done():
                if self._terminal is None:
                    self.request_stop("execution_control_lost")
                    await self.on_stop()
                else:
                    try:
                        async with asyncio.timeout(self._config.terminate_timeout):
                            await asyncio.shield(exited)
                    except TimeoutError:
                        await self.on_stop()
            await exited
            try:
                async with asyncio.timeout(self._config.ipc_timeout):
                    await asyncio.shield(self._read_task)
            except TimeoutError:
                self._protocol_failed = True
            terminal = self._terminal
            if self._forced or self._protocol_failed or terminal is None:
                outcome, reason = "unknown", "execution_outcome_unknown"
            elif terminal.outcome == "success" and self._process.returncode != 0:
                outcome, reason = "unknown", "exit_after_success_failed"
            else:
                outcome, reason = terminal.outcome, terminal.reason
            return ProcessResult(
                execution_id=self.execution_id,
                outcome=outcome,
                reason=reason,
                exit_code=self._process.returncode,
                stop_reason=self._reason or (terminal.stop_reason if terminal is not None else ""),
            )
        finally:
            if not exited.done():
                exited.cancel()
            await asyncio.gather(exited, return_exceptions=True)

    async def wait(self) -> ProcessResult:
        if self._result_task is not None:
            return await asyncio.shield(self._result_task)
        await self.on_stop()
        return ProcessResult(
            execution_id=self.execution_id,
            outcome="unknown" if self._process is not None else "failed",
            reason="execution_outcome_unknown"
            if self._process is not None
            else "process_not_started",
            exit_code=self._process.returncode if self._process is not None else None,
            stop_reason=self._reason,
        )

    def request_stop(self, reason: str) -> None:
        if self._close_task is None:
            self._reason = reason
            self._close_task = asyncio.create_task(self._close(), name="execution_process_close")
            self._close_task.add_done_callback(self._observe)

    async def _close(self) -> None:
        if self._server is not None:
            self._server.close()
        if self._start_task is not None and not self._start_task.done():
            self._start_task.cancel()
            await asyncio.gather(self._start_task, return_exceptions=True)
        if self._spawn_task is not None:
            result = (await asyncio.gather(self._spawn_task, return_exceptions=True))[0]
            if isinstance(result, asyncio.subprocess.Process):
                self._process = result
                self._spawned.set()
        process = self._process
        if process is not None and process.returncode is None:
            graceful = False
            if self._writer is not None:
                try:
                    await send(
                        self._writer,
                        ProcessMessage(
                            execution_id=self.execution_id,
                            kind="stop",
                            reason=self._reason,
                        ),
                        self._config.ipc_timeout,
                    )
                    graceful = True
                except (OSError, TimeoutError, ValueError):
                    pass
            if graceful:
                try:
                    async with asyncio.timeout(self._config.shutdown_timeout):
                        await process.wait()
                except TimeoutError:
                    pass
            if process.returncode is None:
                self._forced = True
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    async with asyncio.timeout(self._config.terminate_timeout):
                        await process.wait()
                except TimeoutError:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    await process.wait()

        # The child is reaped before the socket and pending authentication tasks are released.
        if self._writer is not None:
            self._writer.close()
            try:
                async with asyncio.timeout(self._config.ipc_timeout):
                    await self._writer.wait_closed()
            except (OSError, TimeoutError):
                pass
        pending = tuple(self._accept_tasks)
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if self._read_task is not None and not self._read_task.done():
            try:
                async with asyncio.timeout(self._config.ipc_timeout):
                    await asyncio.shield(self._read_task)
            except TimeoutError:
                self._protocol_failed = True
                self._read_task.cancel()
                await asyncio.gather(self._read_task, return_exceptions=True)
        if self._server is not None:
            async with asyncio.timeout(self._config.ipc_timeout):
                await self._server.wait_closed()
        self._ticket = self._application = ""
        self._request = None

    async def on_stop(self) -> None:
        self.request_stop("host_shutdown")
        assert self._close_task is not None
        await wait_for_cleanup(self._close_task)
