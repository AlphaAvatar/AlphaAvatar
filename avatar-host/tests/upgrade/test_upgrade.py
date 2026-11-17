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
"""Upgrading between two builds of one version: the target prepared whole beside the current
installation, by its own plan and commands, with the default bundle and credentials read under
the lock, then current switched once; anything failing or stopping it before that leaves the
installation as it was."""

from __future__ import annotations

import contextlib
import fcntl
import functools
import http.server
import json
import os
import platform
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
from pathlib import Path

import pytest
from upgrade_samples import VERSION, build, installed, listing

from alphaavatar.host.configs import application_paths
from alphaavatar.host.configs.bundles import read_settings
from alphaavatar.host.configs.template import create_bundle
from alphaavatar.host.tools.setup import environment
from alphaavatar.host.tools.setup.environment import SetupError, Sources
from alphaavatar.host.tools.setup.plan import plan_install
from alphaavatar.host.tools.upgrade import upgrade
from alphaavatar.host.tools.upgrade.upgrade import Source, package_file

pytestmark = pytest.mark.skipif(
    (platform.system(), platform.machine()) != ("Linux", "x86_64"),
    reason="the package is the Linux x86_64 one",
)


@pytest.fixture
def builds(tmp_path: Path):
    """Two builds of one version, A set up for a bundle needing alpha, current; B's bundle
    needs beta."""
    prefix, log = tmp_path / "prefix", tmp_path / "commands.log"
    first, second = build(tmp_path / "out", "aaaa"), build(tmp_path / "out", "bbbb")
    installation = installed(prefix, first, ("alpha", "host"))
    environ = dict(os.environ, UPGRADE_LOG=str(log), UPGRADE_PREFIX=str(prefix))
    paths = application_paths()  # The test's own home: the default bundle is avatar.
    paths.settings_dir.mkdir(parents=True)
    paths.settings_file.write_text("default_bundle: avatar\n")

    def run(source: Source, **extra: str) -> upgrade.Upgraded:
        return upgrade.upgrade(installation, source, paths=paths, environ=environ | extra)

    return installation, first, second, run, log


def commands(log: Path) -> list[list[str]]:
    return [line.split() for line in log.read_text().splitlines()] if log.exists() else []


def test_the_target_is_prepared_beside_by_its_own_plan_then_current_switches_once(builds) -> None:
    installation, first, second, run, log = builds
    prefix = installation.prefix
    previous = os.readlink(prefix / "current")
    steps: list[tuple[int, str | None]] = []
    upgraded = upgrade.upgrade(
        installation,
        package_file(second.package),
        paths=application_paths(),
        environ=dict(os.environ, UPGRADE_LOG=str(log), UPGRADE_PREFIX=str(prefix)),
        step=lambda number, name, summary: steps.append((number, summary)),
    )
    assert (upgraded.previous, upgraded.current, upgraded.runners) == (first.id, second.id, 2)
    assert upgraded.bundle == "avatar"
    now = os.readlink(prefix / "current")
    assert now.startswith("envs/") and now != previous and upgraded.path == prefix / now
    # The target's own setup planned the bundle; its environment's config check accepted it
    # while current still ran A's.
    assert commands(log) == [
        ["plan:avatar", second.id, previous],
        ["check:avatar", second.id, previous],
    ]
    # Its plan keeps what the current environment holds: the earlier bundle's alpha.
    plan = json.loads((prefix / now / environment.PLAN_FILE).read_text())
    assert (plan["base"], plan["requirements"]) == (second.id, ["alpha", "beta", "host"])
    imported = subprocess.run(
        [prefix / now / "bin" / "python", "-I", "-c", "import alpha, beta"], capture_output=True
    )
    assert imported.returncode == 0, imported.stderr
    assert [number for number, summary in steps if summary is not None] == [1, 2, 3, 4]
    # A stays whole beside B; no stage is left.
    assert sorted(path.name for path in (prefix / "versions").iterdir()) == [first.id, second.id]
    assert sorted(path.name for path in (prefix / "envs").iterdir()) == sorted(
        [previous.removeprefix("envs/"), now.removeprefix("envs/")]
    )
    assert os.readlink(prefix / "current") == now


def test_the_same_build_ends_at_once_and_an_older_version_is_refused(
    builds, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both are told from the file where it is: no copy, no stage made, none removed."""
    installation, first, second, run, log = builds
    prefix = installation.prefix
    older = build(tmp_path / "out", "cccc", version="9.9.8")
    # What a killed run left: only a run that makes a stage removes it.
    left = prefix / "versions" / f"{environment.INSTALL_STAGE}left"
    left.mkdir()
    (left / environment.INSTALL_MARK).touch()
    before, made = listing(prefix), []

    def spied(name: str, called):
        def call(*args, **kwargs):
            made.append(name)
            return called(*args, **kwargs)

        return call

    monkeypatch.setattr(tempfile, "mkdtemp", spied("mkdtemp", tempfile.mkdtemp))
    monkeypatch.setattr(shutil, "copyfile", spied("copyfile", shutil.copyfile))
    same = upgrade.Upgraded(first.id, first.id, bundle="avatar")
    assert run(package_file(first.package)) == same
    # Told by the file once it matches its SHA-256 only, here as for --check.
    for told in (run, upgrade.inspect):
        with pytest.raises(SetupError, match="does not match its SHA-256"):
            told(package_file(first.package, sha256="0" * 64))
    with pytest.raises(SetupError, match="older than the current 9.9.9; upgrade does not go back"):
        run(package_file(older.package))
    assert made == [] and listing(prefix) == before and commands(log) == []


def test_what_unpacks_is_this_runs_copy_checked_again(
    builds, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The file replaced after it was read where it is: the copy made of it fails its SHA-256."""
    installation, first, second, run, log = builds
    before, read = listing(installation.prefix), upgrade._read

    def then_replaced(package: Path, expected: str) -> dict:
        found = read(package, expected)
        package.write_bytes(first.package.read_bytes())
        return found

    monkeypatch.setattr(upgrade, "_read", then_replaced)
    with pytest.raises(SetupError, match="does not match its SHA-256"):
        run(package_file(second.package))
    assert listing(installation.prefix) == before


def test_a_setup_just_before_the_lock_is_what_the_target_plans_and_checks(
    builds, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A setup of the build current runs makes bundle new the default, storing a credential
    with it, as the upgrade is about to take the lock: the target plans and checks new, with
    that credential, and refusing new leaves A current."""
    installation, first, second, run, log = builds
    prefix, paths = installation.prefix, application_paths()
    stored = {"UPGRADE_SECRET": "before"}
    create_bundle(paths, "old", avatar_id="old", make_default=True, credentials=stored)
    previous, before = os.readlink(prefix / "current"), listing(prefix)
    locked = upgrade.locked

    @contextlib.contextmanager
    def after_a_setup(where: Path):
        # That setup runs whole first, under the same lock: A's own plan, already installed,
        # then new enabled, its credential stored by the same settings replacement.
        plan = plan_install(first.catalog, ("alpha", "host"), base=first.id)
        environment.install(
            installation,
            plan,
            Sources(str(first.directory)),
            check=lambda env: None,
            enable=lambda: create_bundle(
                paths,
                "new",
                avatar_id="new",
                make_default=True,
                credentials={"UPGRADE_SECRET": "after"},
            ),
        )
        with locked(where):
            yield

    monkeypatch.setattr(upgrade, "locked", after_a_setup)
    with pytest.raises(SetupError, match="fails check new"):
        run(package_file(second.package), UPGRADE_REFUSE="new")
    assert read_settings(paths)["default_bundle"] == "new"
    assert commands(log) == [
        ["plan:new:after", second.id, previous],
        ["check:new:after", second.id, previous],
    ]
    assert os.readlink(prefix / "current") == previous and listing(prefix) == before


class Interrupted(BaseException):
    pass


@pytest.mark.parametrize(
    "failure",
    [
        "checksum",
        "not a package",
        "base does not run",
        "plan refused",
        "artifact missing",
        "another build's artifact",
        "configuration refused",
        "current does not run it",
        "interrupted",
    ],
)
def test_a_failure_leaves_current_and_removes_only_what_the_run_made(
    builds, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    installation, first, second, run, log = builds
    prefix = installation.prefix
    previous, before = os.readlink(prefix / "current"), listing(prefix)
    source, extra = package_file(second.package), {}
    why = {
        "checksum": "does not match its SHA-256",
        "not a package": "Not an AlphaAvatar package: no manifest",
        "base does not run": f"does not run AlphaAvatar {VERSION}",
        "plan refused": "does not plan bundle avatar:\n  error: ValidationError",
        "artifact missing": "Cannot get beta-1.0-py3-none-any.whl",
        "another build's artifact": "host-1.0-py3-none-any.whl: not the planned file",
        "configuration refused": "fails check avatar:\n  error: ValidationError",
        "current does not run it": "current/bin/alphaavatar does not run AlphaAvatar",
        "interrupted": "",
    }[failure]
    if failure == "checksum":
        source = package_file(second.package, sha256="0" * 64)
    elif failure == "not a package":
        second.package.write_bytes(b"not a package")
        Path(f"{second.package}.sha256").write_text(
            f"{environment.sha256(second.package)}  {second.package.name}\n"
        )
    elif failure == "base does not run":
        source = package_file(build(tmp_path / "broken", "bbbb", runs=False).package)
    elif failure == "plan refused":
        extra = {"UPGRADE_PLAN": "refuse"}
    elif failure == "artifact missing":
        (second.directory / "beta-1.0-py3-none-any.whl").unlink()
    elif failure == "another build's artifact":
        source = package_file(second.package, artifacts=str(first.directory))
    elif failure == "configuration refused":
        extra = {"UPGRADE_CHECK": "refuse"}
    elif failure == "current does not run it":
        reports = upgrade._reports

        def through_current(command: Path, *args) -> None:
            if "current" in command.parts:
                raise SetupError(f"{command} does not run AlphaAvatar {VERSION}")
            reports(command, *args)

        monkeypatch.setattr(upgrade, "_reports", through_current)
    else:
        checked = upgrade.check_environment

        def interrupted(*args):
            checked(*args)
            raise Interrupted

        monkeypatch.setattr(upgrade, "check_environment", interrupted)
    with pytest.raises((SetupError, Interrupted)) as failed:
        run(source, **extra)
    assert why in str(failed.value)
    if failure in ("plan refused", "configuration refused"):
        assert str(failed.value).endswith(upgrade.FIX)
    # A is current and whole; what the run made is gone, the lock it took aside.
    assert os.readlink(prefix / "current") == previous
    assert listing(prefix) == before


@pytest.mark.parametrize("call", ["rename", "mkdtemp"])
@pytest.mark.parametrize("moved", ["versions", "envs"])
def test_a_signal_as_a_directory_appears_finds_it_this_runs(
    builds, monkeypatch: pytest.MonkeyPatch, moved: str, call: str
) -> None:
    """SIGTERM the moment a directory of the run appears in versions/ or envs/, its stage made
    or the target's base or environment renamed into place: the run stops before the switch
    and removes it; A stays current and runs."""
    installation, first, second, run, log = builds
    prefix = installation.prefix
    previous, before = os.readlink(prefix / "current"), listing(prefix)
    module = os if call == "rename" else tempfile
    made = getattr(module, call)

    def signalled(*args, **kwargs):
        found = made(*args, **kwargs)
        appeared = args[1] if call == "rename" else found
        if Path(appeared).parent == prefix / moved:
            signal.raise_signal(signal.SIGTERM)
        return found

    def stop(signum: int, frame: object) -> None:
        raise SystemExit(128 + signum)  # As the upgrade command has SIGTERM end it.

    monkeypatch.setattr(module, call, signalled)
    handler = signal.signal(signal.SIGTERM, stop)
    try:
        with pytest.raises(SystemExit):
            run(package_file(second.package))
    finally:
        signal.signal(signal.SIGTERM, handler)
    assert os.readlink(prefix / "current") == previous and listing(prefix) == before
    command = prefix / "current" / "bin" / "alphaavatar"
    ran = subprocess.run([command, "--version"], cwd="/", capture_output=True, text=True)
    assert ran.stdout == f"AlphaAvatar {VERSION}\n", ran.stderr


def test_one_installation_per_prefix(builds) -> None:
    installation, first, second, run, log = builds
    before = listing(installation.prefix)
    with (installation.prefix / ".install.lock").open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        with pytest.raises(SetupError, match="Another installation"):
            run(package_file(second.package))
    assert listing(installation.prefix) == before


def test_a_bare_base_upgrades_to_the_target_base(tmp_path: Path) -> None:
    first, second = build(tmp_path / "out", "aaaa"), build(tmp_path / "out", "bbbb")
    installation = installed(tmp_path / "prefix", first, None)
    upgraded = upgrade.upgrade(
        installation,
        package_file(second.package),
        paths=application_paths(),
        environ=dict(os.environ),
    )
    assert (upgraded.previous, upgraded.current, upgraded.bundle) == (first.id, second.id, None)
    assert os.readlink(installation.prefix / "current") == f"versions/{second.id}"
    assert not (installation.prefix / "envs").exists()
    assert (installation.prefix / "versions" / first.id).is_dir()


@pytest.fixture
def releases(tmp_path: Path, owned_addresses: set[object], monkeypatch: pytest.MonkeyPatch):
    """A release channel on loopback, as GitHub lays one out, and the paths it was asked for."""
    root, asked = tmp_path / "github", []

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            asked.append(self.path)

    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Handler, directory=str(root))
    )
    owned_addresses.add(("127.0.0.1", server.server_port))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"

    def loopback(address: tuple[str, int], timeout: object = None, *args: object) -> socket.socket:
        # What urllib connects with: a socket whose connect the owned addresses still judge.
        connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if isinstance(timeout, int | float):
            connection.settimeout(timeout)
        connection.connect(address)
        return connection

    monkeypatch.setattr(socket, "create_connection", loopback)
    for module in (upgrade, environment):
        monkeypatch.setattr(module, "RELEASES", f"{url}/download")
    monkeypatch.setattr(upgrade, "LATEST", f"{url}/latest/download")

    def publish(made) -> None:
        """``made`` as release v9.9.9, the latest: its files, and its manifest beside them."""
        for directory in (root / "download" / f"v{VERSION}", root / "latest" / "download"):
            shutil.copytree(made.directory, directory, dirs_exist_ok=True)
            manifest = json.loads(
                subprocess.run(
                    ["tar", "-xzOf", made.package, "--wildcards", "*/manifest.json"],
                    capture_output=True,
                    check=True,
                ).stdout
            )
            (directory / upgrade.MANIFEST).write_text(json.dumps(manifest))

    yield publish, asked
    server.shutdown()
    server.server_close()


def test_a_release_is_told_by_its_manifest_before_its_package_downloads(
    builds, releases, tmp_path: Path
) -> None:
    installation, first, second, run, log = builds
    publish, asked = releases
    target = build(tmp_path / "release", "dddd", release=True)
    publish(target)
    assert upgrade.inspect(upgrade.release())["id"] == target.id
    assert asked == [f"/latest/download/{upgrade.MANIFEST}"]
    asked.clear()
    assert run(upgrade.release()).current == target.id
    package = f"/download/v{VERSION}/alphaavatar-{VERSION}-linux-x86_64.tar.gz"
    assert asked[:3] == [f"/latest/download/{upgrade.MANIFEST}", f"{package}.sha256", package]
    # The build's own wheels come from its release.
    assert f"/download/v{VERSION}/host-1.0-py3-none-any.whl" in asked
    asked.clear()
    # Run by the target now current: the same release again downloads nothing.
    now = environment.Installation(
        installation.prefix, installation.prefix / "versions" / target.id
    )
    again = upgrade.upgrade(now, upgrade.release(VERSION), paths=application_paths(), environ={})
    assert again == upgrade.Upgraded(target.id, target.id, bundle="avatar")
    assert asked == [f"/download/v{VERSION}/{upgrade.MANIFEST}"]
    # The build that ran before refuses to: current is not what runs it.
    with pytest.raises(SetupError, match=f"runs AlphaAvatar {target.id}, not AlphaAvatar"):
        run(upgrade.release())
    with pytest.raises(SetupError, match=r"Release v9\.9\.8 publishes no linux-x86_64 package"):
        upgrade.release("9.9.8")
