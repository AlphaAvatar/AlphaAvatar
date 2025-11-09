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
import asyncio
import signal
import threading

from livekit.agents import ipc, utils, worker
from livekit.agents.cli import _run, log, proto
from livekit.agents.inference_runner import _InferenceRunner

from alphaavatar.agents.log import logger


def run_avatar_worker(args: proto.CliArgs, *, jupyter: bool = False) -> None:
    log.setup_logging(args.log_level, args.devmode, args.console)
    args.opts.validate_config(args.devmode)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    if args.console:
        print(_run._esc(34) + "=" * 50 + _run._esc(0))
        print(_run._esc(34) + "     AlphAavatar - Console" + _run._esc(0))
        print(_run._esc(34) + "=" * 50 + _run._esc(0))
        print("Press [Ctrl+B] to toggle between Text/Audio mode, [Q] to quit.\n")

    worker = AvatarWorker(args.opts, devmode=args.devmode, register=args.register, loop=loop)

    loop.set_debug(args.asyncio_debug)
    loop.slow_callback_duration = 0.1  # 100ms
    utils.aio.debug.hook_slow_callbacks(2)

    @worker.once("worker_started")
    def _worker_started() -> None:
        if args.simulate_job and args.reload_count == 0:
            loop.create_task(worker.simulate_job(args.simulate_job))

    try:

        def _signal_handler() -> None:
            raise KeyboardInterrupt

        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, _signal_handler)

    except NotImplementedError:
        # TODO(theomonnom): add_signal_handler is not implemented on win
        pass

    async def _worker_run(worker: AvatarWorker) -> None:
        try:
            await worker.run()
        except Exception:
            logger.exception("worker failed")

    watch_client = None
    if args.watch:
        from livekit.agents.cli.watcher import WatchClient

        watch_client = WatchClient(worker, args, loop=loop)
        watch_client.start()

    try:
        main_task = loop.create_task(_worker_run(worker), name="agent_runner")
        try:
            loop.run_until_complete(main_task)
        except KeyboardInterrupt:
            pass

        try:
            if not args.devmode:
                loop.run_until_complete(worker.drain(timeout=args.opts.drain_timeout))

            loop.run_until_complete(worker.aclose())

            if watch_client:
                loop.run_until_complete(watch_client.aclose())
        except KeyboardInterrupt:
            if not jupyter:
                logger.warning("exiting forcefully")
                import os

                os._exit(1)  # TODO(theomonnom): add aclose(force=True) in worker
    finally:
        if jupyter:
            loop.close()  # close can only be called from the main thread
            return  # noqa: B012

        try:
            tasks = asyncio.all_tasks(loop)
            for task in tasks:
                task.cancel()

            loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
        finally:
            loop.close()


class AvatarWorker(worker.Worker):
    def __init__(
        self,
        opts: worker.WorkerOptions,
        *,
        devmode: bool = True,
        register: bool = True,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        super().__init__(opts, devmode=devmode, register=register, loop=loop)

        if len(_InferenceRunner.registered_runners) > 0:
            self._inference_executor = ipc.inference_proc_executor.InferenceProcExecutor(
                runners=_InferenceRunner.registered_runners,
                initialize_timeout=opts.initialize_process_timeout,
                close_timeout=5,
                memory_warn_mb=opts.job_memory_warn_mb // 2,
                memory_limit_mb=0,  # no limit
                ping_interval=5,
                ping_timeout=60,
                high_ping_threshold=2.5,
                mp_ctx=self._mp_ctx,
                loop=self._loop,
                http_proxy=opts.http_proxy or None,
            )

        self._proc_pool = ipc.proc_pool.ProcPool(
            initialize_process_fnc=opts.prewarm_fnc,
            job_entrypoint_fnc=opts.entrypoint_fnc,
            num_idle_processes=worker._WorkerEnvOption.getvalue(
                opts.num_idle_processes, self._devmode
            ),
            loop=self._loop,
            job_executor_type=opts.job_executor_type,
            inference_executor=self._inference_executor,
            mp_ctx=self._mp_ctx,
            initialize_timeout=opts.initialize_process_timeout,
            close_timeout=opts.shutdown_process_timeout,
            memory_warn_mb=opts.job_memory_warn_mb,
            memory_limit_mb=opts.job_memory_limit_mb,
            http_proxy=opts.http_proxy or None,
        )
