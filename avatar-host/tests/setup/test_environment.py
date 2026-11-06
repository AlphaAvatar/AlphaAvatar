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
import json
import os
import shutil
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
    (base / "share" / "alphaavatar").mkdir(parents=True)
    (base / "share" / "alphaavatar" / "manifest.json").write_text('{"id": "base"}')
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

    # This plan's directory, not setup's: left as it is.
    partial = installation.environment(plan)
    (partial / "lib").mkdir(parents=True)
    (partial / "lib" / "half-written").write_text("")
    with pytest.raises(SetupError, match="exists and is not setup's"):
        install(installation, plan, sources, check=lambda env: None, enable=lambda: None)
    assert (partial / "lib" / "half-written").exists()
    # Setup's, without plan.json: a run that died; the next one rebuilds it, and removes the
    # stage a killed run left, but not a directory without the mark.
    (partial / environment.OWNER).touch()
    stale, foreign = (
        installation.prefix / "envs" / ".setup-dead",
        installation.prefix / "envs" / ".setup-other",
    )
    for directory in (stale, foreign):
        directory.mkdir()
    (stale / environment.OWNER).touch()
    install(installation, plan, sources, check=lambda env: None, enable=lambda: None)
    assert not (partial / "lib" / "half-written").exists() and not stale.exists()
    assert foreign.exists() and installation.current() == partial.resolve()


def test_a_plan_made_before_another_setup_finished_keeps_what_that_one_installed(
    setup_layout,
) -> None:
    installation, everything, sources, _ = setup_layout
    alpha = everything.artifacts[:1]

    def plan(requirements: tuple[str, ...]) -> Plan:
        chosen = tuple(a for a in everything.artifacts if a.name in requirements)
        return Plan("1.0", "linux-x86_64", "base", tuple(sorted(set(requirements))), chosen)

    # A remote setup planned alpha alone, then waited; another setup installed both meanwhile.
    remote = Plan("1.0", "linux-x86_64", "base", ("alpha",), alpha)
    full = install(installation, everything, sources, check=lambda env: None, enable=lambda: None)
    with pytest.raises(SetupError, match="holds beta; plan them"):
        install(installation, remote, sources, check=lambda env: None, enable=lambda: None)
    # Resumed, it plans again under the lock with what is installed: the bundle keeps beta.
    replans = []
    target = install(
        installation,
        remote,
        sources,
        check=lambda env: None,
        enable=lambda: None,
        replan=lambda kept: replans.append(kept) or plan(("alpha", *kept)),
    )
    assert replans == [("alpha", "beta")] and target == full
    assert installation.current() == full.resolve()
    imported = subprocess.run([target / "bin" / "python", "-I", "-c", "import beta"])
    assert imported.returncode == 0
    # A base that changed meanwhile is not this setup's to switch from.
    os.symlink("versions/newer", installation.prefix / "next")
    (installation.prefix / "versions" / "newer").mkdir()
    os.replace(installation.prefix / "next", installation.prefix / "current")
    with pytest.raises(SetupError, match="runs AlphaAvatar newer now, not base"):
        install(installation, remote, sources, check=lambda env: None, enable=lambda: None)


def test_what_is_checked_is_what_installs_and_unknown_paths_are_left_alone(
    setup_layout, monkeypatch: pytest.MonkeyPatch
) -> None:
    installation, plan, sources, wheels = setup_layout
    verified = environment._verified

    def replaced_after(path: Path, artifact: Artifact) -> bool:
        found = verified(path, artifact)
        if found and artifact.name == "alpha":  # The source changes once it is checked.
            source = wheels / artifact.file
            os.replace(wheel(wheels.parent, "alpha"), source)
            with zipfile.ZipFile(source, "a") as archive:
                archive.writestr("alpha/other.py", "VALUE = 2\n")
        return found

    monkeypatch.setattr(environment, "_verified", replaced_after)
    target = install(installation, plan, sources, check=lambda env: None, enable=lambda: None)
    found = list(target.glob("lib/python*/site-packages/alpha/other.py"))
    assert found == []  # The checked copy installed, not what replaced the source.

    # A current that is not a link setup or install.sh made, or points elsewhere: left alone.
    current = installation.prefix / "current"
    current.unlink()
    current.mkdir()
    (current / "kept").write_text("")
    with pytest.raises(SetupError, match="not a link setup or install.sh made"):
        install(installation, plan, sources, check=lambda env: None, enable=lambda: None)
    assert (current / "kept").exists()
    shutil.rmtree(current)
    os.symlink(str(wheels), current)
    with pytest.raises(SetupError, match="points outside"):
        install(installation, plan, sources, check=lambda env: None, enable=lambda: None)
    assert os.readlink(current) == str(wheels)


def test_an_environment_reached_through_a_link_is_neither_reused_nor_switched_to(
    setup_layout, tmp_path: Path
) -> None:
    installation, plan, sources, wheels = setup_layout
    prefix = installation.prefix
    # Outside the prefix, the plan's environment as setup leaves one: marked, plan.json last.
    outside = tmp_path / "outside"
    (outside / environment.PLAN_FILE).parent.mkdir(parents=True)
    (outside / environment.PLAN_FILE).write_text(json.dumps(plan.document()))
    (outside / environment.OWNER).touch()
    before = sorted(str(path.relative_to(outside)) for path in outside.rglob("*"))
    checked: list[Path] = []
    (prefix / "envs").mkdir()
    installation.environment(plan).symlink_to(outside)
    assert not installation.reusable(plan)
    with pytest.raises(SetupError, match="exists and is not setup's"):
        install(installation, plan, sources, check=checked.append, enable=lambda: None)
    assert checked == [] and os.readlink(prefix / "current") == "versions/base"
    assert installation.current() == installation.base
    installation.environment(plan).unlink()

    # envs itself a link elsewhere: nothing is made through it.
    (prefix / "envs").rmdir()
    (prefix / "envs").symlink_to(outside.parent)
    with pytest.raises(SetupError, match="not this installation's own directory"):
        install(installation, plan, sources, check=checked.append, enable=lambda: None)
    (prefix / "envs").unlink()
    assert checked == [] and os.readlink(prefix / "current") == "versions/base"

    # A current spelled versions/<name> whose directory is a link out is no version of this one.
    (prefix / "versions" / "linked").symlink_to(outside)
    (prefix / "current").unlink()
    (prefix / "current").symlink_to("versions/linked")
    with pytest.raises(SetupError, match="points outside"):
        install(installation, plan, sources, check=checked.append, enable=lambda: None)
    assert checked == [] and os.readlink(prefix / "current") == "versions/linked"
    assert sorted(str(path.relative_to(outside)) for path in outside.rglob("*")) == before


def test_the_lock_is_never_opened_through_a_link_nor_truncated(
    setup_layout, tmp_path: Path
) -> None:
    installation, plan, sources, wheels = setup_layout
    lock, outside = installation.prefix / ".install.lock", tmp_path / "outside-file"
    outside.write_text("someone's data\n")
    lock.symlink_to(outside)
    with pytest.raises(SetupError, match="is not a lock file"):
        install(installation, plan, sources, check=lambda env: None, enable=lambda: None)
    assert outside.read_text() == "someone's data\n" and lock.is_symlink()
    lock.unlink()
    lock.write_text("held\n")
    install(installation, plan, sources, check=lambda env: None, enable=lambda: None)
    assert lock.read_text() == "held\n"
