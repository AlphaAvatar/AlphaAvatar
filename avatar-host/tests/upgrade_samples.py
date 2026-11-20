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
"""Builds of one version, as build.sh lays them out, and an installation of one.

A build is its package (manifest, catalog, commands, Python) with its .sha256, and its own
wheels beside it. The commands stand in for AlphaAvatar's, each recording in ``UPGRADE_LOG``
what ran and where current pointed: the base's answers ``--version``, ``--help`` and
``setup <bundle> --plan`` with the requirements the build plans; the environment's, from the
``host`` wheel each build makes, ``--version``, setup's probe and ``config check``; each
records ``UPGRADE_SECRET`` too when it is set, as a credential the target reads.
``UPGRADE_LOAD``, Python code ``UPGRADE_PYTHON`` runs with the bundle's name, stands in for how
the plan and the check load the bundle: they record what it prints as the credential read.
``UPGRADE_PLAN=refuse`` and ``UPGRADE_CHECK=refuse`` make the plan and the check refuse;
``UPGRADE_REFUSE=<bundle>`` makes the check refuse that bundle alone.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from alphaavatar.host.tools.setup.environment import Installation, Sources, install
from alphaavatar.host.tools.setup.plan import plan_install

VERSION = "9.9.9"
BASE = """\
#!/bin/sh
log() {{ [ -z "$UPGRADE_LOG" ] || echo "$1 {id} $(readlink "$UPGRADE_PREFIX/current")" >> "$UPGRADE_LOG"; }}
case "$1" in
  --version) echo "AlphaAvatar {shown}" ;;
  --help) echo "usage: alphaavatar" ;;
  setup)
    [ -z "$UPGRADE_LOAD" ] || UPGRADE_SECRET=$("$UPGRADE_PYTHON" -c "$UPGRADE_LOAD" "$2") || exit 2
    log "plan:$2${{UPGRADE_SECRET:+:$UPGRADE_SECRET}}"
    if [ "$UPGRADE_PLAN" = refuse ]; then
      printf '%s\\n' '{{"error": {{"diagnostic": "  error: ValidationError\\n    voice.stt.model: Field required"}}}}'
      exit 2
    fi
    printf '%s\\n' '{{"requirements": {needs}}}' ;;
  *) exit 2 ;;
esac
"""
MAIN = """\
import json, os, sys

def main():
    args = sys.argv[1:]
    if args == ["--version"]:
        return print("AlphaAvatar {version}")
    current = os.readlink(os.environ["UPGRADE_PREFIX"] + "/current")
    secret = os.environ.get("UPGRADE_SECRET")
    if os.environ.get("UPGRADE_LOAD"):
        import subprocess
        load = [os.environ["UPGRADE_PYTHON"], "-c", os.environ["UPGRADE_LOAD"], args[2]]
        secret = subprocess.run(load, capture_output=True, text=True, check=True).stdout.strip()
    with open(os.environ["UPGRADE_LOG"], "a") as log:
        log.write(f"check:{{args[2]}}{{':' + secret if secret else ''}} {id} {{current}}\\n")
    if os.environ.get("UPGRADE_CHECK") == "refuse" or args[2] == os.environ.get("UPGRADE_REFUSE"):
        why = "  error: ValidationError\\n    loop.init_config.model: Field required"
        print(json.dumps({{"valid": False, "error": {{"diagnostic": why}}}}))
        return 2
    print(json.dumps({{"valid": True, "inference": {{"a": 1, "b": 2}}}}))
"""


@dataclass(frozen=True, slots=True)
class Build:
    id: str
    package: Path
    directory: Path  # The build's files: the package, its .sha256 and its own wheels.

    @property
    def catalog(self) -> dict:
        with tarfile.open(self.package) as archive:
            member = next(m for m in archive if m.name.endswith("/catalog.json"))
            return json.load(archive.extractfile(member))


def _wheel(directory: Path, name: str, files: dict[str, str]) -> Path:
    path = directory / f"{name}-1.0-py3-none-any.whl"
    info = f"{name}-1.0.dist-info"
    files = {
        **files,
        f"{info}/METADATA": f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n",
        f"{info}/WHEEL": "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    with zipfile.ZipFile(path, "w") as archive:
        for member, text in files.items():
            archive.writestr(member, text)
        archive.writestr(f"{info}/RECORD", "".join(f"{m},,\n" for m in [*files, f"{info}/RECORD"]))
    return path


def _add(archive: tarfile.TarFile, name: str, text: str, mode: int = 0o644) -> None:
    data = text.encode()
    member = tarfile.TarInfo(name)
    member.size, member.mode = len(data), mode
    archive.addfile(member, io.BytesIO(data))


def build(
    root: Path,
    commit: str,
    *,
    version: str = VERSION,
    needs: tuple[str, ...] = ("beta", "host"),
    release: bool = False,
    runs: bool = True,
) -> Build:
    """A build of ``commit``: a release's (named by its version) or a CI build's. The bundle it
    plans needs ``needs``; ``runs=False`` makes its command report another version."""
    id = f"{version}-{commit}"
    name = f"alphaavatar-{version if release else id}-linux-x86_64"
    directory = root / id
    directory.mkdir(parents=True)
    wheels = {
        "alpha": _wheel(directory, "alpha", {"alpha/__init__.py": "VALUE = 1\n"}),
        "beta": _wheel(directory, "beta", {"beta/__init__.py": "VALUE = 2\n"}),
        # The environment's command, this build's own: its wheel differs from another build's.
        "host": _wheel(
            directory,
            "host",
            {
                "alphaavatar/host/main.py": MAIN.format(version=version, id=id),
                "alphaavatar/host/tools/setup/probe.py": "",
            },
        ),
    }
    catalog = {
        "format": 1,
        "version": version,
        "platform": "linux-x86_64",
        "base": ["core"],
        "requirements": {key: [key] for key in wheels},
        "distributions": {"core": {"version": version}}
        | {
            key: {
                "version": "1.0",
                "file": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size": path.stat().st_size,
                "url": None,
                "glibc": None,
                "cpu": [],
            }
            for key, path in wheels.items()
        },
    }
    manifest = {
        "id": id,
        "version": version,
        "commit": commit,
        "release": f"v{version}" if release else None,
        "platform": "linux-x86_64",
        "glibc": "2.17",
        "cpu": [],
        "imports": ["json"],
    }
    package = directory / f"{name}.tar.gz"
    shown = version if runs else "0.0.0"
    with tarfile.open(package, "w:gz") as archive:
        _add(archive, f"{name}/share/alphaavatar/manifest.json", json.dumps(manifest, indent=2))
        _add(archive, f"{name}/share/alphaavatar/catalog.json", json.dumps(catalog))
        # The package's own Python, as relocatable as the real one: no link out of it.
        python = f'#!/bin/sh\nexec "{sys._base_executable}" "$@"\n'
        _add(archive, f"{name}/python/bin/python3", python, 0o755)
        command = BASE.format(id=id, shown=shown, needs=json.dumps(list(needs)))
        _add(archive, f"{name}/bin/alphaavatar", command, 0o755)
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    Path(f"{package}.sha256").write_text(f"{digest}  {package.name}\n")
    return Build(id, package, directory)


def installed(prefix: Path, build: Build, requirements: tuple[str, ...] | None) -> Installation:
    """The build installed into ``prefix`` as install.sh does, then, given ``requirements``,
    set up as setup does: current is their environment."""
    (prefix / "versions").mkdir(parents=True)
    with tarfile.open(build.package) as archive:
        archive.extractall(prefix / "versions", filter="data")
        top = archive.getnames()[0].split("/")[0]
    base = prefix / "versions" / build.id
    os.rename(prefix / "versions" / top, base)
    os.symlink(f"versions/{build.id}", prefix / "current")
    installation = Installation(prefix, base)
    if requirements is not None:
        plan = plan_install(build.catalog, requirements, base=build.id)
        sources = Sources(str(build.directory))
        install(installation, plan, sources, check=lambda env: None, enable=lambda: None)
    return installation


def listing(root: Path) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*"))


def stopped_rmtree(*marks: str):
    """shutil.rmtree, stopped by Ctrl-C partway, as it may take any order: what it removed
    first is the mark, when one is inside what it was given, or else one of what it holds."""
    rmtree = shutil.rmtree

    def stopped(path, *args, **kwargs) -> None:
        path = Path(path)
        if found := [path / mark for mark in marks if (path / mark).is_file()]:
            found[0].unlink()
        elif children := sorted(path.iterdir()):
            if children[0].is_dir() and not children[0].is_symlink():
                rmtree(children[0])
            else:
                children[0].unlink()
        else:
            path.rmdir()
        raise KeyboardInterrupt

    return stopped
