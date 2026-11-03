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
"""doctor: read-only and offline, config check's selection rules, exit codes, one report.

How complete this machine's installation is belongs to the machine: package checks are only
asserted where a test removes a package itself. Runtime checks run model-free runners from
``doctor_runner_samples`` and ``inference_runner_samples``; no model is ever cached here.
"""

from __future__ import annotations

import asyncio
import json
import multiprocessing as mp
import os
import shutil
import signal
import statistics
import tempfile
import threading
import time
from collections.abc import Awaitable, Callable
from hashlib import sha256
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from config_samples import CONFIG, LOOP, SECRETS, files, write
from doctor_runner_samples import HeldRunner, WitnessRunner
from inference_runner_samples import EchoRunner, FailingCloseRunner, FailingInitRunner

# Imported at collection: configuration plugins adjust process variables while importing (O-2).
import alphaavatar.agents.configs  # noqa: F401
import alphaavatar.host.doctor as host_doctor
from alphaavatar.agents.runtime.inference import RunnerProbe
from alphaavatar.host.cli.app import main
from alphaavatar.host.cli.commands.doctor import GROUPS
from alphaavatar.host.doctor import CHECKS, Check, CheckStatus, Report

IDS = [spec.id for spec in CHECKS]
STATIC = [spec.id for spec in CHECKS if not spec.needs_runtime]
UNVERIFIED = ("models.runners", "services.external", "devices.media")
PATHS = ("paths.home", "paths.cache", "paths.workspace")


@pytest.fixture
def disk() -> SimpleNamespace:
    """Free space is an input of the machine; tests choose it."""
    space = SimpleNamespace(free=64 << 30)
    with mock.patch.object(shutil, "disk_usage", lambda path: space):
        yield space


def doctor(capsys: pytest.CaptureFixture, *argv: str) -> tuple[int, dict[str, dict], str]:
    """One run's text, checked against the very report it shows, and that report as JSON.

    A static run is repeated with --json, which prints the same report. Runtime figures differ
    between runs, so a runtime run is not repeated.
    """
    runtime = "--runtime" in argv
    reports: list[Report] = []
    if runtime:
        real = host_doctor.diagnose_runtime

        async def shown(*args: object, **kwargs: object) -> Report:
            reports.append(await real(*args, **kwargs))
            return reports[-1]
    else:
        real = host_doctor.diagnose

        def shown(*args: object, **kwargs: object) -> Report:
            reports.append(real(*args, **kwargs))
            return reports[-1]

    with mock.patch.object(host_doctor, real.__name__, shown):
        code = main(["doctor", *argv])
    text = capsys.readouterr().out
    raw = json.dumps(reports[0].to_dict())
    report = json.loads(raw)
    if not runtime:
        assert main(["doctor", *argv, "--json"]) == code
        assert json.loads(capsys.readouterr().out) == report
    assert [check["id"] for check in report["checks"]] == (IDS if runtime else STATIC)
    assert code in (130, 1 if report["status"] == "FAIL" else 0)
    lines = text.splitlines()
    # Grouped for reading; a pass is one line, anything else shows its details and next step.
    headings = [line for line in lines if line.startswith("    ") and line[4] != " "]
    groups = [group for group, ids in GROUPS.items() if runtime or "runtime.models" not in ids]
    assert [heading.strip() for heading in headings] == groups
    for check in report["checks"]:
        heading = f"{check['status']}  {check['id'].ljust(21)}  {check['summary']}"
        assert f"      {heading}" in lines
        shown_lines = [line.strip() in check["details"] for line in lines]
        assert any(shown_lines) == (check["status"] != "PASS" and bool(check["details"]))
        # Every runner as its own line; one that did not pass says why and what to do.
        width = max((len(runner["method"]) for runner in check["runners"]), default=0)
        for runner in check["runners"]:
            line = (
                f"        {runner['status']}  {runner['method'].ljust(width)}  {runner['summary']}"
            )
            assert line in lines
            if runner["status"] != "PASS":
                assert all(detail in text for detail in runner["details"])
                assert runner["action"] is None or f"-> {runner['action']}" in text
    return code, {check["id"]: check for check in report["checks"]}, text + raw


def test_without_a_configuration_doctor_says_how_to_create_one_and_checks_the_rest(
    tmp_path: Path, home: Path, sandbox: list[str], disk: object, capsys: pytest.CaptureFixture
) -> None:
    before = files(tmp_path)
    _, checks, _ = doctor(capsys)
    # A missing configuration warns; everything that needs none is still checked.
    statuses = {check: report["status"] for check, report in checks.items()}
    assert statuses.pop("packages.alphaavatar") != "SKIP"
    assert statuses == {
        "system.platform": "PASS",
        "python.version": "PASS",
        "config.load": "WARN",
        "config.runners": "SKIP",
        "packages.capabilities": "SKIP",
        "paths.home": "PASS",
        "paths.cache": "PASS",
        "paths.workspace": "SKIP",
        "models.runners": "SKIP",
        "services.external": "SKIP",
        "devices.media": "SKIP",
    }
    assert "`alphaavatar config init <name> --avatar-id <id>`" in checks["config.load"]["action"]
    assert (
        checks["paths.home"]["summary"] == f"{home}  (not created yet; created when first needed)"
    )
    # Read-only and offline: no file or directory, no client, no local socket.
    assert (files(tmp_path), sandbox) == (before, [])
    # Warnings and unverified checks never fail a report; one failed check does.
    warned = (Check("a", CheckStatus.WARN, "a"), Check("b", CheckStatus.SKIP, "b"))
    failed = (Check("a", CheckStatus.PASS, "a"), Check("b", CheckStatus.FAIL, "b"))
    assert (Report(warned).exit_code, Report(failed).exit_code) == (0, 1)

    # Listing runs nothing, so even unreadable settings cannot stop it.
    (home / "settings").mkdir(parents=True)
    (home / "settings" / "settings.yaml").write_text("default_bundle: [\n")
    assert main(["doctor", "--list", "--json"]) == 0
    specs = json.loads(capsys.readouterr().out)["checks"]
    assert [spec["id"] for spec in specs] == IDS
    assert [spec["id"] for spec in specs if spec["needs_runtime"]] == [
        "runtime.models",
        "runtime.cleanup",
    ]
    for argv in (["alpha"], ["--runtime"]):
        with pytest.raises(SystemExit) as invalid:
            main(["doctor", "--list", *argv])
        assert invalid.value.code == 2


def test_doctor_selects_and_loads_configurations_as_config_check_does(
    tmp_path: Path,
    home: Path,
    sandbox: list[str],
    credentials: object,
    disk: object,
    capsys: pytest.CaptureFixture,
) -> None:
    assert main(["config", "init", "alpha", "--avatar-id", "alpha"]) == 0
    single = write(tmp_path / "single.json", CONFIG | {"avatar": {"id": "single"}})
    capsys.readouterr()
    before = files(tmp_path)
    # The default bundle, a named one, an override alone (default bundle) and a file.
    for argv in ([], ["alpha"], ["avatar.id=renamed"], [str(single), "voice.tts.speed=1.3"]):
        assert main(["config", "check", *argv, "--json"]) == 0
        summary = json.loads(capsys.readouterr().out)
        _, checks, _ = doctor(capsys, *argv)
        source = summary["config"]
        origin = f"bundle {source['bundle']}" if source["bundle"] else f"file {source['file']}"
        origin += " (default)" if source["default"] else ""
        assert checks["config.load"]["summary"] == f"{origin} loaded and validated"
        assert checks["config.load"]["details"] == [f"avatar {summary['avatar_id']}"]
        assert checks["paths.workspace"]["summary"].startswith(f"{summary['workspace']}  (")
        # What static checks cannot see is reported as not verified, never as passing.
        assert [checks[check]["status"] for check in UNVERIFIED] == ["SKIP"] * 3
    # The file's remote vector store and MCP server are named, though not contacted.
    assert {"Qdrant", "1 MCP server"} <= set(checks["services.external"]["details"])

    # Refusals match config check's, including a built-in plugin's own schema, with exit 1.
    no_model = write(tmp_path / "no-model.json", CONFIG | {"loop": {"plugin": "realtime"}})
    before = files(tmp_path)
    for argv in (["nope"], ["alpha", "persona.init_config.unknown=1"], [str(no_model)]):
        assert main(["config", "check", *argv]) == 2
        refused = capsys.readouterr().err
        code, checks, _ = doctor(capsys, *argv)
        assert code == 1 and checks["config.load"]["status"] == "FAIL"
        assert all(line in refused for line in checks["config.load"]["details"])
        assert checks["config.load"]["action"]
        assert checks["packages.capabilities"]["status"] == "SKIP"
    assert "fields: loop.init_config.model" in checks["config.load"]["details"]
    assert (files(tmp_path), sandbox) == (before, [])

    # Unreadable settings do not stop a named bundle; the home check says what to fix.
    settings = home / "settings" / "settings.yaml"
    settings.write_text("default_bundle: [\n")
    _, checks, _ = doctor(capsys, "alpha")
    assert checks["config.load"]["status"] == "PASS"
    assert checks["paths.home"]["status"] == "WARN"
    assert checks["paths.home"]["action"].startswith(f"Fix or remove {settings};")


def test_provider_backends_follow_defaults_and_skip_what_start_does_not_create(
    tmp_path: Path, credentials: object, disk: object, capsys: pytest.CaptureFixture
) -> None:
    without_mcp = CONFIG["tools"] | {"mcp": {"enabled": False}}

    def providers(model: dict, **sections: object) -> tuple[list[str], dict[str, dict]]:
        loop = {"plugin": "realtime", "init_config": {"model": model}}
        value = CONFIG | {"loop": loop, "tools": without_mcp} | sections
        _, checks, _ = doctor(capsys, str(write(tmp_path / "avatar.json", value)))
        found = checks["services.external"]["details"]
        return [line for line in found if line.startswith("model providers")], checks

    # The loop alone: memory and persona from another plugin add no store embeddings.
    others = {"memory": {"plugin": "custom"}, "persona": {"plugin": "custom"}}
    # A task naming only its model takes the schema's defaults, as if they were written out.
    implicit, _ = providers({"model": "m"}, **others)
    explicit, _ = providers({"model": "m", "backend": "langchain", "provider": "openai"}, **others)
    assert implicit == explicit == ["model providers (langchain)"]
    # The store embeddings alone: the loop names another backend; they use the default.
    assert providers({"model": "m", "backend": "openai"})[0] == [
        "model providers (langchain, openai)"
    ]
    # Switched-off processors and disabled tools are not created: their leftovers need nothing.
    leftover = {"tasks": {"leftover": {"model": "m", "backend": "nowhere"}}}
    off = {"enabled": False, "provider": {"gateway": leftover}}
    memory = CONFIG["memory"] | {"init_config": {"tool": off}}
    persona = {"init_config": {"profiler": off}}
    rag = {"plugin": None, "init_config": {"summary": {"model": "m", "backend": "nowhere"}}}
    found, checks = providers(
        LOOP["init_config"]["model"],
        memory=memory,
        persona=persona,
        tools=without_mcp | {"rag": rag},
    )
    assert found == ["model providers (langchain)"]
    assert not any("nowhere" in line for line in checks["packages.capabilities"]["details"])


def test_missing_packages_unusable_paths_and_env_files_fail_with_a_next_step(
    tmp_path: Path,
    home: Path,
    credentials: object,
    disk: SimpleNamespace,
    capsys: pytest.CaptureFixture,
) -> None:
    assert main(["config", "init", "alpha", "--avatar-id", "alpha"]) == 0
    capsys.readouterr()
    real = metadata.distribution

    def uninstalled(name: str) -> metadata.Distribution:
        # The RTC extra, and the default provider backend the template's tasks rely on.
        if name.lower() in ("livekit", "langchain-openai"):
            raise metadata.PackageNotFoundError(name)
        return real(name)

    with mock.patch.object(metadata, "distribution", uninstalled):
        code, checks, _ = doctor(capsys)
    capabilities = checks["packages.capabilities"]
    assert code == 1 and capabilities["status"] == "FAIL"
    assert {"rtc: livekit is not installed", "providers: langchain-openai is not installed"} <= set(
        capabilities["details"]
    )
    # Other packages missing on this machine may be named too.
    assert "'alpha-avatar-host[livekit]'" in capabilities["action"]
    assert "'alpha-avatar-plugins-provider[langchain]'" in capabilities["action"]

    # Low free space warns.
    disk.free = 1 << 20
    _, checks, _ = doctor(capsys)
    assert [checks[check]["status"] for check in PATHS] == ["WARN"] * 3
    assert all(checks[check]["action"] for check in PATHS)

    # A home behind a link without a target cannot be created: it fails, not passes.
    disk.free = 64 << 30
    shutil.move(home, tmp_path / "moved")
    home.symlink_to(tmp_path / "missing")
    code, checks, _ = doctor(capsys)
    assert code == 1
    assert [checks[check]["status"] for check in ("paths.home", "paths.cache")] == ["FAIL"] * 2
    assert checks["paths.home"]["summary"] == f"{home} is a symbolic link that does not resolve"
    assert checks["paths.cache"]["action"]

    # An unreadable .env is reported in the same machine-readable report.
    env_file = tmp_path / "broken.env"
    env_file.write_bytes(b"OPENAI_API_KEY=\xff\xfe\n")
    with mock.patch.dict(os.environ, {"ENV_FILE": str(env_file)}):
        code, checks, output = doctor(capsys)
    assert code == 1
    load = checks["config.load"]
    assert (load["status"], load["summary"]) == ("FAIL", "The environment file could not be read")
    assert load["details"][0] == "error: UnicodeDecodeError"
    assert load["action"].startswith("Fix the file ENV_FILE names")
    assert [checks[check]["status"] for check in PATHS] == ["SKIP"] * 3
    assert "Traceback" not in output


def test_doctor_reports_pass_the_configuration_output_boundary(
    tmp_path: Path, credentials: object, disk: object, capsys: pytest.CaptureFixture
) -> None:
    # A credential reused as the Avatar ID, and terminal escapes in the home and file paths.
    home = tmp_path / "home\x1b[2Jdir"
    value = CONFIG | {"application": {"home": str(home)}, "avatar": {"id": SECRETS["vdb"]}}
    config = write(tmp_path / "avatar\x1b[31m.json", value)
    _, checks, output = doctor(capsys, str(config))
    assert checks["config.load"]["details"] == ["avatar [redacted]"]
    assert checks["paths.home"]["details"][0].startswith("chosen by the configuration file;")
    assert "[redacted]" in checks["paths.workspace"]["summary"]
    assert [name for name, secret in SECRETS.items() if secret in output] == []
    assert "\x1b" not in output and "\\u001b" not in output


@pytest.fixture
def probes(
    monkeypatch: pytest.MonkeyPatch, owned_endpoints: set[object], socket_root: Path
) -> Callable[..., None]:
    """Plan model-free runners after the plugins' own, each offering the probe given with it.

    The runtime's endpoint is the test's own, so executors may reach it; ``socket_root`` keeps
    its socket short and proves that Doctor's temporary directories are gone afterwards.
    """
    from alphaavatar.agents.runtime.inference import (
        InferenceExecutor,
        bootstrap as inference_bootstrap,
    )

    selected: list[type] = []
    plan = lambda config: tuple(selected)  # noqa: E731
    monkeypatch.setitem(inference_bootstrap._runner_bootstraps, "test.doctor", plan)
    connect = InferenceExecutor.__init__

    def owned(executor: InferenceExecutor, endpoint: str, *args: object, **kwargs: object) -> None:
        owned_endpoints.add(endpoint)
        connect(executor, endpoint, *args, **kwargs)

    monkeypatch.setattr(InferenceExecutor, "__init__", owned)

    def select(*chosen: tuple[type, RunnerProbe]) -> None:
        selected[:] = [runner for runner, _ in chosen]
        for runner, probe in chosen:
            monkeypatch.setattr(runner, "probe", classmethod(lambda cls, probe=probe: probe))

    return select


def sample(
    runner: type, check: Callable[[bytes | None], str] | None = None
) -> tuple[type, RunnerProbe]:
    def answered(answer: bytes | None) -> str:
        if answer != b"sample":
            raise ValueError("not the sample back")
        return "answered"

    probe = RunnerProbe(
        model=runner.__name__,
        request=b"sample",
        check=check or answered,
        missing=lambda models_dir: None,
        audio_seconds=0.5,
        device="test",
    )
    return runner, probe


WITNESS = sample(WitnessRunner, check=lambda answer: answer.decode())
TURN = "alphaavatar.router.turn_taking.smart_turn_v3"


def test_runtime_checks_run_only_selected_probed_runners_offline_through_the_executor(
    tmp_path: Path,
    home: Path,
    credentials: object,
    disk: object,
    probes: Callable[..., None],
    capsys: pytest.CaptureFixture,
) -> None:
    from alphaavatar.agents.runtime.inference import (
        INFERENCE_ENDPOINT_ENV,
        InferenceExecutor,
        InferenceRuntime,
    )

    # Two workers configured; Doctor starts one, so the configuration's limit is not tested.
    workers = {"inference": {"methods": {WitnessRunner.INFERENCE_METHOD: {"workers": 2}}}}
    config = write(tmp_path / "avatar.json", CONFIG | {"runtime": workers})
    probes(WITNESS)
    _, checks, _ = doctor(capsys, str(config))
    # Static checks point at the runtime checks for the runners with a probe.
    assert checks["models.runners"]["action"].startswith(
        f"`alphaavatar doctor {config} --runtime` runs the 2 with a probe;"
    )
    before = files(tmp_path)
    requests: list[str] = []
    real = InferenceExecutor.do_inference

    async def counted(executor: InferenceExecutor, method: str, data: bytes) -> bytes | None:
        requests.append(method)
        return await real(executor, method, data)

    closed: list[str] = []

    def closing(owner: type) -> Callable[[object], Awaitable[None]]:
        close = owner.close

        async def recorded(instance: object) -> None:
            closed.append(owner.__name__)
            await close(instance)

        return recorded

    # Without offline loading here, a missing model is a warning: start would download it.
    online = {name: value for name, value in os.environ.items() if "OFFLINE" not in name}
    with (
        mock.patch.dict(os.environ, online, clear=True),
        mock.patch.object(InferenceExecutor, "do_inference", counted),
        mock.patch.object(InferenceExecutor, "close", closing(InferenceExecutor)),
        mock.patch.object(InferenceRuntime, "close", closing(InferenceRuntime)),
    ):
        code, checks, _ = doctor(capsys, str(config), "--runtime")
        assert {"ALPHAAVATAR_MODEL_OFFLINE", "HF_HUB_OFFLINE"}.isdisjoint(os.environ)
    assert code == 0 and checks["runtime.models"]["status"] == "WARN"
    runners = {runner["method"]: runner for runner in checks["runtime.models"]["runners"]}
    # The selected runners only: Silero VAD has a probe, but this configuration has no VAD.
    assert {TURN, "test.doctor.witness"} <= set(runners)
    assert "alphaavatar.voice.vad.silero" not in runners
    # Without a probe a runner never starts, and is never shown as passing.
    assert {
        runner["summary"] for method, runner in runners.items() if method.startswith("alphaavatar")
    } - {runners[TURN]["summary"]} == {"No local probe: not started, so not verified"}
    # A missing model is reported, not fetched: nothing is created, locked or downloaded.
    turn = runners[TURN]
    assert (turn["status"], turn["initialize_seconds"], turn["inference_seconds"]) == (
        "WARN",
        None,
        [],
    )
    assert turn["summary"].startswith("Smart Turn v3.2-cpu is not cached")
    assert f"then run `alphaavatar doctor {config} --runtime` again" in turn["action"]
    assert (files(tmp_path), (home / "cache").exists()) == (before, False)

    # The fixed request went through the executor to a runner process of its own, which
    # loaded models from the configured cache, offline, in a temporary workspace.
    witness = runners["test.doctor.witness"]
    seen = json.loads(witness["output"])
    assert requests == ["test.doctor.witness"] * 6
    assert seen["pid"] != os.getpid() and seen["request"] == sha256(b"sample").hexdigest()
    assert seen["starts"] == 1 and closed == ["InferenceExecutor", "InferenceRuntime"]
    assert (seen["offline"], seen["hub_offline"]) == (True, "1")
    assert seen["models"] == str(home / "cache" / "models")
    assert Path(seen["workspace"]).parent == Path(tempfile.gettempdir())
    assert not Path(seen["workspace"]).exists()
    later = witness["inference_seconds"][1:]
    assert witness["status"] == "PASS" and len(later) == 5
    assert witness["initialize_seconds"] > 0
    assert witness["real_time_factor"] == statistics.median(later) / 0.5
    assert (witness["audio_seconds"], witness["device"]) == (0.5, "test")
    assert checks["runtime.cleanup"]["status"] == "PASS"
    assert INFERENCE_ENDPOINT_ENV not in os.environ

    # With offline loading, as this environment has it, start fails without the model.
    assert main(["doctor", str(config), "--runtime", "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    (models,) = [check for check in report["checks"] if check["id"] == "runtime.models"]
    (turn,) = [runner for runner in models["runners"] if runner["method"] == TURN]
    assert turn["status"] == "FAIL" and "start fails without it" in turn["action"]


def test_runtime_failures_timeouts_and_budgets_are_reported_and_reclaimed(
    tmp_path: Path,
    home: Path,
    credentials: object,
    disk: object,
    probes: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    from alphaavatar.host.doctor import runtime as doctor_runtime

    def reject(answer: bytes | None) -> str:
        raise ValueError("an echo is not a witness answer")

    config = str(write(tmp_path / "avatar.json", CONFIG))
    monkeypatch.setattr(doctor_runtime, "PROBE_SECONDS", 2.0)
    # Each failure stays its own: the runners after it still run, and every one is closed.
    chosen = (
        sample(FailingInitRunner),
        sample(EchoRunner, check=reject),
        sample(FailingCloseRunner),
        sample(HeldRunner),
        WITNESS,
    )
    probes(*chosen)
    code, checks, output = doctor(capsys, config, "--runtime")
    assert code == 1 and checks["runtime.models"]["status"] == "FAIL"
    runners = {runner["method"]: runner for runner in checks["runtime.models"]["runners"]}
    assert [runners[runner.INFERENCE_METHOD]["status"] for runner, _ in chosen] == [
        "FAIL",
        "FAIL",
        "PASS",
        "FAIL",
        "PASS",
    ]
    failed = runners["test.failing_init"]
    assert failed["summary"] == "FailingInitRunner: failed while starting"
    assert "error: RuntimeError" in failed["details"] and failed["inference_seconds"] == []
    echo = runners["test.echo"]
    assert echo["summary"] == (
        "EchoRunner: the answer breaks the probe's contract: an echo is not a witness answer"
    )
    assert len(echo["inference_seconds"]) == 1
    held = runners["test.doctor.held"]
    assert held["summary"] == "HeldRunner: no result within 2 s, while starting"
    # A runner whose close fails: reported, with error types and code locations only.
    cleanup = checks["runtime.cleanup"]
    assert cleanup["status"] == "FAIL"
    assert "test.failing_close: the runtime did not close cleanly" in cleanup["details"]
    assert "private" not in output

    # The whole run has a budget too: what it leaves out is named, not passed.
    monkeypatch.setattr(doctor_runtime, "RUNTIME_SECONDS", 1.0)
    monkeypatch.setattr(doctor_runtime, "PROBE_SECONDS", 1.0)
    probes(sample(HeldRunner), WITNESS)
    code, checks, _ = doctor(capsys, config, "--runtime")
    runners = {runner["method"]: runner for runner in checks["runtime.models"]["runners"]}
    held, witness = runners["test.doctor.held"], runners["test.doctor.witness"]
    assert code == 1 and held["summary"] == "HeldRunner: no result within 1 s, while starting"
    assert (witness["status"], witness["summary"]) == (
        "SKIP",
        "Not run: the 1 s budget of the runtime checks ran out",
    )
    assert checks["runtime.cleanup"]["summary"].startswith("1 runtime closed:")


def test_interrupting_runtime_checks_closes_what_runs_and_reports_the_rest(
    tmp_path: Path,
    home: Path,
    credentials: object,
    disk: object,
    probes: Callable[..., None],
    socket_root: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    from alphaavatar.agents.runtime.inference import INFERENCE_ENDPOINT_ENV

    config = str(write(tmp_path / "avatar.json", CONFIG))
    probes(sample(HeldRunner), WITNESS)

    def interrupt() -> None:
        # Ctrl+C once the held runner is starting, as a terminal delivers it.
        deadline = time.monotonic() + 30
        while not list(socket_root.glob("alphaavatar-doctor-*/held.entered")):
            if time.monotonic() > deadline:
                return
            time.sleep(0.002)
        os.kill(os.getpid(), signal.SIGINT)

    thread = threading.Thread(target=interrupt)
    thread.start()
    try:
        code, checks, output = doctor(capsys, config, "--runtime")
    finally:
        thread.join()
    assert code == 130 and output.lstrip().startswith("STOPPED  doctor:")
    runners = {runner["method"]: runner for runner in checks["runtime.models"]["runners"]}
    held, witness = runners["test.doctor.held"], runners["test.doctor.witness"]
    assert (held["status"], held["summary"]) == ("SKIP", "Interrupted while starting")
    assert (witness["status"], witness["summary"]) == ("SKIP", "Not run: interrupted")
    # The held runner's process, socket and temporary workspace are gone (see fixtures).
    assert checks["runtime.cleanup"]["status"] == "PASS"
    assert INFERENCE_ENDPOINT_ENV not in os.environ

    # An App cancelling the call: what runs is closed before the cancellation propagates.
    async def cancelled() -> None:
        task = asyncio.create_task(host_doctor.diagnose_runtime(config))
        async with asyncio.timeout(30):
            while not list(socket_root.glob("alphaavatar-doctor-*/held.entered")):
                await asyncio.sleep(0.002)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancelled())
    assert (mp.active_children(), list(socket_root.iterdir())) == ([], [])
    assert INFERENCE_ENDPOINT_ENV not in os.environ
