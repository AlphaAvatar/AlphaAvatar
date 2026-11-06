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
"""Doctor's diagnostic process: the session runs in a process of Doctor's own.

Model downloads switched off, the inference endpoint and the captured logs all belong to
that process, so the caller's environment, loggers and children stay as they were; the
endpoints a Host caller exports are not inherited, and the caller's terminal shows its report
alone: what the process and its runners print goes to a file beside the report, whose last line
names why a process that ends without a report did. The
process leads its own process group, so the terminal's Ctrl+C reaches only the caller, which
asks it to stop by closing a pipe; a caller that dies closes it too. The caller owns the
temporary directory, which is also the process's temporary root (its runtime's socket goes
there unless that path would be too long), the snapshot it runs and the group: whatever the
process leaves behind is reclaimed with them and reported.
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import os
import pickle
import shutil
import signal
import tempfile
from collections.abc import Sequence
from dataclasses import replace
from typing import TYPE_CHECKING

from alphaavatar.core.cleanup import wait_for_cleanup

from . import session
from .enums import CheckStatus
from .schemas import Check

if TYPE_CHECKING:
    from multiprocessing.connection import Connection

    from alphaavatar.host.configs import ApplicationConfig, ConfigSource

CLOSE_SECONDS = 60.0  # Past the session's budget: closing what ran, then the group goes.
# Both switch off the model resolvers' downloads; the second also Hugging Face libraries'.
_OFFLINE = ("ALPHAAVATAR_MODEL_OFFLINE", "HF_HUB_OFFLINE")
_REPORT = "report.pickle"
_OUTPUT = "output.log"


async def diagnose(
    config: ApplicationConfig,
    source: ConfigSource,
    services: Sequence[tuple[str, str]],
    *,
    stop: asyncio.Event,
    downloads: bool = False,
) -> dict[str, Check]:
    """The session's checks from a diagnostic process; cancelling this ends that process too.

    The snapshot it runs is ``config`` moved onto a temporary workspace (``session.isolate``),
    so the services it was authorized for are the ones it can reach. Its runners start from
    the model cache alone unless ``downloads``, as a person agreed, lets them fetch what it
    lacks there, as `start` does.
    """
    run = tempfile.mkdtemp(prefix="alphaavatar-doctor-")
    problems: list[str] = []  # What reclaiming found
    checks: dict[str, Check] | None = None
    missing = "the diagnostic process left no report"
    try:
        snapshot, rebound = session.isolate(config, os.path.join(run, "workspace"))
        # A download is part of its runners' start, bounded as start bounds it.
        initialize = config.avatar.runtime.inference.initialize_timeout if downloads else None
        limits = session.budget(initialize)
        checks, missing = await _supervise(
            (snapshot.payload, source, tuple(services), rebound, run, limits, downloads),
            limits.total + CLOSE_SECONDS,
            stop,
            problems,
        )
    finally:
        try:
            shutil.rmtree(run)
        except Exception as error:
            problems.append(f"temporary directory {run} not removed: {type(error).__name__}")
    if checks is None:
        checks = {
            check_id: Check(
                check_id,
                CheckStatus.FAIL,
                "The check could not complete",
                (missing,),
                "Report this with the output of `alphaavatar doctor --json`",
            )
            for check_id in ("session.start", "models.runners", "session.scenarios")
        }
        checks["session.cleanup"] = Check("session.cleanup", CheckStatus.SKIP, "Not reported")
    if problems:
        cleanup = checks["session.cleanup"]
        checks["session.cleanup"] = replace(
            cleanup,
            status=CheckStatus.FAIL,
            summary="Closing the diagnostic session left something behind",
            details=(*cleanup.details, *problems),
            action="Report this with the output of `alphaavatar doctor --json`",
        )
    return checks


async def _supervise(
    args: tuple[object, ...], limit: float, stop: asyncio.Event, problems: list[str]
) -> tuple[dict[str, Check] | None, str]:
    """The process's report, or None and why there is none."""
    context = mp.get_context("spawn")
    reader, writer = context.Pipe(duplex=False)
    process = context.Process(target=_main, args=(reader, *args), name="doctor:session")
    loop = asyncio.get_running_loop()
    exited = loop.create_future()
    try:
        process.start()
    finally:
        reader.close()

    def ended() -> None:
        loop.remove_reader(process.sentinel)
        exited.done() or exited.set_result(None)

    loop.add_reader(process.sentinel, ended)
    try:
        waiter = asyncio.ensure_future(stop.wait())
        try:
            await asyncio.wait((exited, waiter), timeout=limit, return_when=asyncio.FIRST_COMPLETED)
        finally:
            waiter.cancel()
        if not exited.done():
            # Asked to stop, or over its budget: it closes what runs and still reports.
            writer.close()
            await asyncio.wait((exited,), timeout=CLOSE_SECONDS)
    except asyncio.CancelledError:
        writer.close()
        await wait_for_cleanup(
            asyncio.ensure_future(asyncio.wait((exited,), timeout=CLOSE_SECONDS))
        )
        raise
    finally:
        writer.close()
        loop.remove_reader(process.sentinel)
        _reclaim(process, problems)
    path = os.path.join(args[4], _REPORT)
    if process.exitcode != 0 or not os.path.exists(path):
        why = f"the diagnostic process exited with code {process.exitcode}"
        # Ended on its own, not killed: where an uncaught error ends, its output does.
        last = _last_line(os.path.join(args[4], _OUTPUT)) if process.exitcode > 0 else ""
        return None, f"{why}: {last}" if last else why
    with open(path, "rb") as stream:
        return pickle.load(stream), ""


def _last_line(path: str) -> str:
    try:
        with open(path, "rb") as stream:
            stream.seek(max(0, os.fstat(stream.fileno()).st_size - 4096))
            lines = stream.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return ""
    return next((line.strip()[:500] for line in reversed(lines) if line.strip()), "")


def _reclaim(process: mp.process.BaseProcess, problems: list[str]) -> None:
    """The process and its group: what is still there after closing is killed and named."""
    if process.is_alive():
        _kill(process.pid, process)
        problems.append(f"the diagnostic process did not exit within {CLOSE_SECONDS:g} s: killed")
    process.join()
    try:
        os.killpg(process.pid, 0)
    except (ProcessLookupError, PermissionError):
        return  # The group is gone: its runners went with it.
    _kill(process.pid, None)
    problems.append("processes the diagnostic process started were still running: killed")


def _kill(group: int, process: mp.process.BaseProcess | None) -> None:
    try:
        os.killpg(group, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        if process is not None:
            process.kill()


def _main(
    stop: Connection,
    payload: str,
    source: ConfigSource,
    services: tuple[tuple[str, str], ...],
    rebound: tuple[str, ...],
    run: str,
    limits: session.Budget,
    downloads: bool = False,
) -> None:
    """The diagnostic process: its own group, downloads off unless allowed, the session, its
    report."""
    os.setsid()
    # The caller's terminal carries its report alone: what this process or its runners print,
    # a runner's failure its report names too, goes to the run's output file.
    output = os.open(os.path.join(run, _OUTPUT), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.dup2(output, 1)
    os.dup2(output, 2)
    os.close(output)
    from alphaavatar.agents.runtime.inference.bootstrap import INFERENCE_PLAN_ENV
    from alphaavatar.agents.runtime.inference.protocol import INFERENCE_ENDPOINT_ENV
    from alphaavatar.core.log.records import LOG_ENDPOINT_ENV

    if not downloads:
        os.environ.update(dict.fromkeys(_OFFLINE, "1"))
    # A Host running Doctor exports its own inference runtime and log receiver; this process
    # and its runners use their own, never the caller's.
    for name in (INFERENCE_ENDPOINT_ENV, INFERENCE_PLAN_ENV, LOG_ENDPOINT_ENV):
        os.environ.pop(name, None)
    # Temporary files of this process and its runners go where the caller removes them.
    os.environ["TMPDIR"] = os.path.join(run, "tmp")
    os.mkdir(os.environ["TMPDIR"], 0o700)
    tempfile.tempdir = None
    from alphaavatar.host.configs import restore_application

    from .transport import LogTimings

    config = restore_application(payload)
    with LogTimings() as logs:
        checks = asyncio.run(_serve(stop, config, source, services, rebound, limits, logs))
    with open(os.path.join(run, _REPORT), "wb") as stream:
        pickle.dump(checks, stream)


async def _serve(
    stop: Connection,
    config: ApplicationConfig,
    source: ConfigSource,
    services: tuple[tuple[str, str], ...],
    rebound: tuple[str, ...],
    limits: session.Budget,
    logs: object,
) -> dict[str, Check]:
    asked = asyncio.Event()
    loop = asyncio.get_running_loop()

    def stopping() -> None:
        loop.remove_reader(stop.fileno())
        asked.set()

    # The caller closes its end to ask for a stop; so does its exit, however it ends.
    loop.add_reader(stop.fileno(), stopping)
    try:
        return await session.diagnose_session(
            config, source, services, rebound, limits=limits, stop=asked, logs=logs
        )
    finally:
        loop.remove_reader(stop.fileno())
