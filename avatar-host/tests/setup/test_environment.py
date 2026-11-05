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
"""Plans and their installation: deterministic, checked before the switch, enabled last."""

from __future__ import annotations

import fcntl
import hashlib
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from alphaavatar.host.setup import environment
from alphaavatar.host.setup.environment import Installation, SetupError, Sources, install
from alphaavatar.host.setup.plan import Artifact, Plan, PlanError, plan_install

CATALOG = {
    "format": 1,
    "version": "1.0",
    "platform": "linux-x86_64",
    "base": ["base-lib", "host"],
    "requirements": {
        "host": ["base-lib", "host"],
        "plugin": ["base-lib", "host", "plugin", "shared"],
        "plugin[local]": ["base-lib", "host", "native", "plugin", "shared"],
    },
    "distributions": {
        "base-lib": {"version": "1"},
        "host": {"version": "1"},
        "native": {
            "version": "2",
            "file": "native-2-cp313-cp313-manylinux_2_28_x86_64.whl",
            "sha256": "b" * 64,
            "size": 20,
            "url": "https://files.invalid/native.whl",
            "glibc": "2.28",
            "cpu": ["avx2"],
        },
        "plugin": {
            "version": "1",
            "file": "plugin-1-py3-none-any.whl",
            "sha256": "a" * 64,
            "size": 10,
            "url": None,
            "glibc": None,
            "cpu": [],
        },
        "shared": {
            "version": "3",
            "file": "shared-3-py3-none-any.whl",
            "sha256": "c" * 64,
            "size": 5,
            "url": "https://files.invalid/shared.whl",
            "glibc": None,
            "cpu": [],
        },
    },
}


def test_a_plan_is_what_the_requirements_need_beyond_the_base_in_one_order() -> None:
    plan = plan_install(CATALOG, ["plugin[local]", "host"], base="b1")
    assert [artifact.name for artifact in plan.artifacts] == ["native", "plugin", "shared"]
    assert (plan.download_bytes, plan.glibc, plan.cpu) == (35, "2.28", ("avx2",))
    again = plan_install(CATALOG, ["host", "plugin[local]", "host"], base="b1")
    assert again.id == plan.id and again.document() == plan.document()
    # Another base or requirement is another plan.
    assert plan_install(CATALOG, ["plugin[local]", "host"], base="b2").id != plan.id
    assert [a.name for a in plan_install(CATALOG, ["plugin"], base="b1").artifacts] == [
        "plugin",
        "shared",
    ]
    with pytest.raises(PlanError, match=r"plugin\[remote\] is not in this package's catalog"):
        plan_install(CATALOG, ["plugin[remote]"], base="b1")
    unsafe = {**CATALOG["distributions"]["plugin"], "file": "../plugin.whl"}
    catalog = CATALOG | {"distributions": CATALOG["distributions"] | {"plugin": unsafe}}
    with pytest.raises(PlanError, match="unsafe file"):
        plan_install(catalog, ["plugin"], base="b1")
    with pytest.raises(PlanError, match="format 1"):
        plan_install(CATALOG | {"format": 2}, ["plugin"], base="b1")


def test_only_a_directory_is_searched_for_every_artifact() -> None:
    plugin, shared = plan_install(CATALOG, ["plugin"], base="b").artifacts
    assert Sources("/cache").candidates(shared) == [
        Path("/cache/shared-3-py3-none-any.whl"),
        "https://files.invalid/shared.whl",
    ]
    # A URL beside the package serves this build's own wheels, as its release does.
    assert Sources("https://ci.invalid/run").candidates(shared) == [
        "https://files.invalid/shared.whl"
    ]
    assert Sources("https://ci.invalid/run/").candidates(plugin) == [
        "https://ci.invalid/run/plugin-1-py3-none-any.whl"
    ]
    assert Sources(release="v1.0").candidates(plugin) == [
        f"{environment.RELEASES}/v1.0/plugin-1-py3-none-any.whl"
    ]
    with pytest.raises(SetupError, match="not published; pass --artifacts"):
        Sources().candidates(plugin)


def wheel(directory: Path, name: str) -> Path:
    path = directory / f"{name}-1.0-py3-none-any.whl"
    info = f"{name}-1.0.dist-info"
    files = {
        f"{name}/__init__.py": b"VALUE = 1\n",
        f"{info}/METADATA": f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n".encode(),
        f"{info}/WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    with zipfile.ZipFile(path, "w") as archive:
        for member, data in files.items():
            archive.writestr(member, data)
        archive.writestr(f"{info}/RECORD", "".join(f"{m},,\n" for m in [*files, f"{info}/RECORD"]))
    return path


def artifact(path: Path) -> Artifact:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return Artifact(path.name.split("-")[0], "1.0", path.name, digest, path.stat().st_size, None)


@pytest.fixture
def setup_layout(tmp_path: Path):
    """A prefix with one base version current, and a plan of two local wheels."""
    prefix, wheels = tmp_path / "prefix", tmp_path / "wheels"
    base = prefix / "versions" / "base"
    (base / "python" / "bin").mkdir(parents=True)
    (base / "python" / "bin" / "python3").symlink_to(sys._base_executable)
    os.symlink("versions/base", prefix / "current")
    wheels.mkdir()
    artifacts = tuple(artifact(wheel(wheels, name)) for name in ("alpha", "beta"))
    plan = Plan("1.0", "linux-x86_64", "base", ("alpha", "beta"), artifacts)
    return Installation(prefix, base), plan, Sources(str(wheels)), wheels


def leftovers(prefix: Path) -> list[str]:
    envs = prefix / "envs"  # Removed too when a first setup made it and failed.
    return sorted(path.name for path in envs.iterdir()) if envs.exists() else []


def test_the_environment_is_checked_before_current_switches_and_enabled_after(setup_layout) -> None:
    installation, plan, sources, wheels = setup_layout
    events: list[tuple[str, Path | None]] = []
    target = install(
        installation,
        plan,
        sources,
        check=lambda env: events.append(("check", installation.current())),
        enable=lambda: events.append(("enable", installation.current())),
    )
    base = installation.base.resolve()
    assert events == [("check", base), ("enable", target.resolve())]
    assert installation.current() == target.resolve() == installation.environment(plan).resolve()
    assert os.readlink(installation.prefix / "current") == f"envs/{plan.id[:16]}"
    assert (target / environment.PLAN_FILE).read_text().startswith("{")
    imported = subprocess.run(
        [target / "bin" / "python", "-I", "-c", "import alpha, beta; print(alpha.VALUE)"],
        capture_output=True,
        text=True,
    )
    assert imported.stdout == "1\n", imported.stderr
    assert os.access(target / "bin" / "alphaavatar", os.X_OK)
    # Local artifacts stay; the stage is gone.
    assert sorted(path.name for path in wheels.iterdir()) == [a.file for a in plan.artifacts]
    assert leftovers(installation.prefix) == [plan.id[:16]]

    # Installed and complete: a second run downloads nothing and checks it again.
    os.replace(installation.prefix / "current", installation.prefix / "kept")
    os.symlink("versions/base", installation.prefix / "current")
    for path in wheels.iterdir():
        path.unlink()
    checked = []
    install(installation, plan, sources, check=checked.append, enable=lambda: None)
    assert checked == [target] and installation.current() == target.resolve()


class Interrupted(BaseException):
    pass


@pytest.mark.parametrize(
    "failure",
    ["check", "enable", "signal after the switch", "corrupt artifact", "signal while fetching"],
)
def test_a_failure_leaves_current_and_removes_only_what_the_run_made(
    setup_layout, failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    installation, plan, sources, wheels = setup_layout
    enabled = []

    def check(env: Path) -> None:
        if failure == "check":
            raise SetupError("the environment fails its check")

    def enable() -> None:
        assert installation.current() == installation.environment(plan).resolve()
        if failure == "enable":
            raise OSError("cannot write the bundle")
        if failure == "signal after the switch":
            raise SystemExit(143)  # What SIGTERM raises in setup.
        enabled.append(True)

    if failure == "corrupt artifact":
        (wheels / plan.artifacts[1].file).write_bytes(b"not the planned file")
    if failure == "signal while fetching":
        fetched = environment.fetch

        def fetch(*args):
            if args[0] is plan.artifacts[1]:
                raise Interrupted
            return fetched(*args)

        monkeypatch.setattr(environment, "fetch", fetch)
    with pytest.raises((SetupError, OSError, SystemExit, Interrupted)):
        install(installation, plan, sources, check=check, enable=enable)
    assert not enabled
    assert os.readlink(installation.prefix / "current") == "versions/base"
    assert sorted(path.name for path in installation.prefix.iterdir()) == [
        ".install.lock",
        "current",
        "versions",
    ]
    assert sorted(path.name for path in wheels.iterdir()) == [a.file for a in plan.artifacts]


def test_one_installation_per_prefix_and_a_dead_partial_is_rebuilt(setup_layout) -> None:
    installation, plan, sources, _ = setup_layout
    (installation.prefix / "envs").mkdir()
    with (installation.prefix / ".install.lock").open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        with pytest.raises(SetupError, match="Another installation"):
            install(installation, plan, sources, check=lambda env: None, enable=lambda: None)
    assert leftovers(installation.prefix) == []
    assert os.readlink(installation.prefix / "current") == "versions/base"

    # This plan's directory without plan.json: a run that died; the next one rebuilds it.
    partial = installation.environment(plan)
    (partial / "lib").mkdir(parents=True)
    (partial / "lib" / "half-written").write_text("")
    install(installation, plan, sources, check=lambda env: None, enable=lambda: None)
    assert not (partial / "lib" / "half-written").exists()
    assert installation.current() == partial.resolve()
