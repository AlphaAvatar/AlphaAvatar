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
"""Each selection resolves by capability type and implementation name in a fresh process:
an installed package's entry point names it, the built-in ones' too. config check, Doctor and
start resolve alike, and plan workers from the runners the resolved plugins use."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from alphaavatar.host.cli.app import main

PROBES = """
from pydantic import BaseModel, ConfigDict

from alphaavatar.agents.runtime.inference import InferenceRunner
from alphaavatar.agents.runtime.plugin import AvatarModule, AvatarModulePlugin


class EchoRunner(InferenceRunner):
    INFERENCE_METHOD = "probe.loop.echo"
    REPLICABLE = True


class Probe(AvatarModulePlugin):
    def __init__(self):
        super().__init__("Probe", "1.0", __name__)

    def get_plugin(self, **kwargs):
        raise AssertionError("resolving creates nothing")


class LoopProbe(Probe):
    def inference_runners(self, config):
        return (EchoRunner,)


class ProviderRunner(InferenceRunner):
    INFERENCE_METHOD = "probe.provider.echo"
    REPLICABLE = True


class ProviderProbe(Probe):
    def inference_runners(self, config):
        return (ProviderRunner,)


class TwoProvidersRunner(InferenceRunner):
    INFERENCE_METHOD = "probe.two.providers"
    PROVIDERS = ((AvatarModule.PROVIDER_LLM, "first"), (AvatarModule.PROVIDER_EMBEDDING, "second"))


class TwoProvidersLoop(Probe):
    def inference_runners(self, config):
        return (TwoProvidersRunner,)


class ChainRunner(InferenceRunner):
    INFERENCE_METHOD = "probe.provider.chain"
    PROVIDERS = ((AvatarModule.PROVIDER_EMBEDDING, "downstream"),)


class ChainProvider(Probe):
    def inference_runners(self, config):
        return (ChainRunner,)


class DownstreamRunner(InferenceRunner):
    INFERENCE_METHOD = "probe.downstream.echo"
    REPLICABLE = True


class DownstreamProvider(Probe):
    def inference_runners(self, config):
        return (DownstreamRunner,)


class MemorySettings(BaseModel):
    model_config = ConfigDict(extra="ignore")
    depth: int = 1


class SchemaMemory(Probe):
    def settings(self, init_config):
        return MemorySettings.model_validate(init_config)
"""
CREDENTIALS = {
    "OPENAI_API_KEY": "sk-fictional",
    "LIVEKIT_URL": "wss://livekit.invalid",
    "LIVEKIT_API_KEY": "lk-fictional",
    "LIVEKIT_API_SECRET": "lk-fictional-secret",
}


def distribution(site: Path, name: str, entry_points: str) -> None:
    """An installed package as importlib.metadata finds one: its module and its dist-info."""
    module = name.replace("-", "_")
    (site / f"{module}.py").write_text(PROBES)
    info = site / f"{module}-1.0.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n")
    (info / "entry_points.txt").write_text(entry_points.replace("MODULE", module))


@pytest.fixture
def run(tmp_path: Path):
    site = tmp_path / "site"
    site.mkdir()
    entrypoint = Path(sys.executable).with_name("alphaavatar")

    def run(*argv: str) -> subprocess.CompletedProcess[str]:
        # Wide: each diagnostic on one line; where a narrow one splits is the renderer's test.
        env = os.environ | CREDENTIALS | {"PYTHONPATH": str(site), "COLUMNS": "1000"}
        return subprocess.run(
            [str(entrypoint), *argv], capture_output=True, text=True, timeout=180, env=env
        )

    def python(script: str, *argv: str) -> subprocess.CompletedProcess[str]:
        env = os.environ | CREDENTIALS | {"PYTHONPATH": str(site)}
        return subprocess.run(
            [sys.executable, "-c", script, *argv],
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
        )

    run.site, run.python = site, python
    assert main(["config", "init", "alpha", "--avatar-id", "alpha"]) == 0
    return run


def test_selections_resolve_by_type_and_name_and_plan_the_runners_they_use(run) -> None:
    # The default bundle: every built-in plugin found by its entry point, its runners planned.
    checked = run("config", "check", "--json")
    assert checked.returncode == 0, checked.stderr
    summary = json.loads(checked.stdout)
    assert summary["inference"]["alphaavatar.voice.vad.silero"] == 1
    assert summary["inference"]["alphaavatar.memory.vdb.lancedb"] == 1

    # Another package's loop, with two workers for the runner it uses, and its memory where a
    # built-in import found Memory before; a switched-off part names nothing installed.
    distribution(
        run.site,
        "probe-plugins",
        "[alphaavatar.loop]\nprobe = MODULE:LoopProbe\n[alphaavatar.memory]\nprobe = MODULE:Probe\n",
    )
    workers = 'runtime.inference.methods={"probe.loop.echo": {"workers": 2}}'
    off = ("tools.mcp.enabled=false", "tools.mcp.plugin=absent", "character.plugin=null")
    checked = run("config", "check", "loop.plugin=probe", "memory.plugin=probe", workers, *off)
    assert checked.returncode == 0, checked.stderr
    checked = run(
        "config", "check", "loop.plugin=probe", "memory.plugin=probe", workers, *off, "--json"
    )
    summary = json.loads(checked.stdout)
    assert (summary["plugins"]["loop"], summary["plugins"]["memory"]["plugin"]) == ("probe",) * 2
    assert summary["inference"]["probe.loop.echo"] == 2
    assert "alphaavatar.memory.vdb.lancedb" not in summary["inference"]  # The probe uses none.


def test_a_provider_backend_plans_its_runners_with_the_rest_wherever_workers_are_planned(
    run,
) -> None:
    # Another package's model provider, named by the loop's model settings, uses a runner;
    # loading, config check, Doctor and start's plan all count it with two workers.
    distribution(
        run.site, "provider-probe", "[alphaavatar.provider.llm]\nprobe = MODULE:ProviderProbe\n"
    )
    selected = (
        "loop.init_config.model.backend=probe",
        'runtime.inference.methods={"probe.provider.echo": {"workers": 2}}',
    )
    checked = run("config", "check", *selected, "--json")
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["inference"]["probe.provider.echo"] == 2
    doctored = run("doctor", *selected, "--json")
    loaded = next(c for c in json.loads(doctored.stdout)["checks"] if c["id"] == "config.load")
    assert loaded["status"] == "PASS", loaded
    # What start launches: the plan prepare_inference_runners leaves for its workers.
    planned = run.python(
        "import json, os, sys\n"
        "from alphaavatar.agents.runtime.inference.bootstrap import (\n"
        "    INFERENCE_PLAN_ENV, prepare_inference_runners,\n"
        ")\n"
        "from alphaavatar.host.configs import load_application, select_configuration\n"
        "config = load_application(select_configuration(None, sys.argv[1:]), sys.argv[1:])\n"
        "prepare_inference_runners(config.avatar)\n"
        "print(os.environ[INFERENCE_PLAN_ENV])",
        *selected,
    )
    assert planned.returncode == 0, planned.stderr
    plan = {item["method"]: item["name"] for item in json.loads(planned.stdout)}
    assert plan["probe.provider.echo"] == "ProviderRunner"
    restored = run.python(
        "import sys\n"
        "from alphaavatar.host.configs import load_application, restore_application, select_configuration\n"
        "config = load_application(select_configuration(None, sys.argv[1:]), sys.argv[1:])\n"
        "print(restore_application(config.payload).avatar.runtime.inference.workers('probe.provider.echo'))",
        *selected,
    )
    assert restored.stdout.strip() == "2", restored.stderr


def test_every_provider_a_runner_names_resolves_and_so_do_their_runners_providers(run) -> None:
    distribution(
        run.site,
        "chain-probe",
        "[alphaavatar.loop]\ntwo = MODULE:TwoProvidersLoop\n"
        "[alphaavatar.provider.llm]\nchain = MODULE:ChainProvider\n",
    )
    # One runner naming two providers: each is resolved at a setting of its own.
    checked = run("config", "check", "loop.plugin=two")
    assert checked.returncode == 2
    for module, name in (("provider.llm", "first"), ("provider.embedding", "second")):
        assert (
            f"loop.plugin (runner probe.two.providers needs {module} {name!r}): "
            f"no installed package provides {module} {name!r}"
        ) in checked.stderr
    # A provider's own runner naming another provider: resolved too, then its runners planned.
    chained = ("loop.init_config.model.backend=chain",)
    checked = run("config", "check", *chained)
    assert checked.returncode == 2
    assert (
        "loop.init_config.model.backend (runner probe.provider.chain needs provider.embedding "
        "'downstream'): no installed package provides provider.embedding 'downstream'"
    ) in checked.stderr
    distribution(
        run.site,
        "downstream-probe",
        "[alphaavatar.provider.embedding]\ndownstream = MODULE:DownstreamProvider\n",
    )
    workers = 'runtime.inference.methods={"probe.downstream.echo": {"workers": 2}}'
    checked = run("config", "check", *chained, workers, "--json")
    assert checked.returncode == 0, checked.stderr
    planned = json.loads(checked.stdout)["inference"]
    assert (planned["probe.provider.chain"], planned["probe.downstream.echo"]) == (1, 2)


def test_another_memorys_own_schema_is_summarized_by_what_it_holds(run) -> None:
    distribution(run.site, "schema-probe", "[alphaavatar.memory]\nschema = MODULE:SchemaMemory\n")
    checked = run("config", "check", "memory.plugin=schema", "memory.init_config.depth=3", "--json")
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["plugins"]["memory"] == {"plugin": "schema", "vdb": None}
    checked = run("config", "check", "memory.plugin=schema", "memory.init_config.depth=deep")
    assert checked.returncode == 2 and "memory.init_config.depth" in checked.stderr


def test_missing_and_duplicate_implementations_fail_where_selected_in_every_command(run) -> None:
    distribution(run.site, "twin-plugins", "[alphaavatar.voice.vad]\nsilero = MODULE:Probe\n")
    duplicate = (
        "voice.vad.plugin: 2 installed packages provide voice.vad 'silero': "
        "alpha-avatar-plugins-voice, twin-plugins"
    )
    missing = "router.plugin: no installed package provides router 'absent'"
    checked = run("config", "check", "router.plugin=absent")
    assert checked.returncode == 2
    assert duplicate in checked.stderr and missing in checked.stderr
    doctored = run("doctor", "router.plugin=absent", "--json")
    loaded = next(c for c in json.loads(doctored.stdout)["checks"] if c["id"] == "config.load")
    assert loaded["status"] == "FAIL"
    assert {duplicate, missing} <= set(loaded["details"])
    started = run("start", "router.plugin=absent")
    assert started.returncode == 2
    assert duplicate in started.stderr and missing in started.stderr
