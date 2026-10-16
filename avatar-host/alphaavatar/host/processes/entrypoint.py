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
import os
import sys

from alphaavatar.core.cleanup import wait_for_cleanup
from alphaavatar.host.application.signals import shutdown_signals

from .channel import receive, send
from .schemas import MAX_LAUNCH_BYTES, MAX_MESSAGE_BYTES, ProcessLaunch, ProcessMessage

logger = logging.getLogger(__name__)


async def _run(launch: ProcessLaunch) -> int:
    stop = asyncio.Event()
    reader, writer = await asyncio.open_connection(
        "127.0.0.1", launch.port, limit=MAX_MESSAGE_BYTES
    )
    lock = asyncio.Lock()
    ready_sent = False

    async def publish(kind: str, *, outcome: str = "", reason: str = "") -> None:
        async with lock:
            await send(
                writer,
                ProcessMessage(
                    execution_id=launch.execution_id,
                    kind=kind,
                    outcome=outcome,
                    reason=reason,
                ),
                launch.ipc_timeout,
            )

    async def ready() -> None:
        nonlocal ready_sent
        if stop.is_set():
            raise RuntimeError("Execution stopped during startup")
        await publish("ready")
        ready_sent = True

    async def controls() -> None:
        try:
            while True:
                message = await receive(reader)
                if (
                    message.kind != "stop"
                    or message.execution_id != launch.execution_id
                    or message.ticket
                    or message.pid
                    or message.outcome
                ):
                    raise ValueError("Invalid execution stop message")
                stop.set()
        except (EOFError, ValueError, OSError):
            # Parent death or a broken channel is not permission to keep running unowned.
            stop.set()

    async def execute() -> str:
        from alphaavatar.host.application.bootstrap import run_execution
        from alphaavatar.host.configs.loader import restore_application

        config = restore_application(launch.application)
        return await run_execution(config, launch.request, stop=stop, ready=ready)

    control = work = None
    outcome, reason = "failed", "execution_start_failed"
    try:
        await send(
            writer,
            ProcessMessage(
                execution_id=launch.execution_id,
                kind="hello",
                ticket=launch.ticket,
                pid=os.getpid(),
            ),
            launch.ipc_timeout,
        )

        launch.ticket = ""
        with shutdown_signals(stop):
            control = asyncio.create_task(controls(), name="execution_parent_control")
            work = asyncio.create_task(execute(), name="execution_runtime")
            try:
                reason = await work
                outcome = "success" if ready_sent else "failed"
            except asyncio.CancelledError:
                stop.set()
                outcome, reason = "unknown", "execution_cancelled"
            except Exception as error:
                # Do not echo launch payloads, credentials, participant metadata, or tool arguments.
                logger.error(
                    "Execution failed execution_id=%s error_type=%s",
                    launch.execution_id,
                    type(error).__name__,
                )
                outcome, reason = "failed", "execution_failed"

        # run_execution returns only after adapters, Engine and Runtime have settled.
        await publish("result", outcome=outcome, reason=reason)
        return 0 if outcome == "success" else 1
    finally:
        stop.set()
        tasks = [task for task in (control, work) if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:

            async def settle() -> None:
                await asyncio.gather(*tasks, return_exceptions=True)

            await wait_for_cleanup(asyncio.create_task(settle(), name="execution_child_cleanup"))
        writer.close()
        try:
            async with asyncio.timeout(launch.ipc_timeout):
                await writer.wait_closed()
        except (OSError, TimeoutError):
            pass


def main() -> int:
    try:
        data = sys.stdin.buffer.readline(MAX_LAUNCH_BYTES + 1)
        if len(data) > MAX_LAUNCH_BYTES or not data.endswith(b"\n"):
            raise ValueError("Invalid execution launch frame")

        launch = ProcessLaunch.model_validate_json(data)

        del data
        logging.basicConfig(
            level=launch.log_level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
        return asyncio.run(_run(launch))
    except (Exception, KeyboardInterrupt) as error:
        logger.error("Execution child stopped error_type=%s", type(error).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
