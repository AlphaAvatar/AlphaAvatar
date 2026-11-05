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
"""The catalog `alphaavatar setup` plans from, for one release on Linux x86_64 (build.sh).

Every requirement setup may ask for, an AlphaAvatar distribution alone or with one extra, maps
to the distributions it needs, followed through uv.lock with markers evaluated for CPython 3.13
on Linux x86_64. Each distribution has exactly one artifact: the best wheel uv.lock records for
manylinux_2_28 or older, else a wheel this build made (AlphaAvatar's own, and sources without
a wheel), with its SHA-256 and size. torch and torchaudio come from torch-cpu.txt instead; the
GUI OpenCV and the CUDA libraries are left out (see build.sh). The roots are pyproject.toml's
setup-catalog group; the base is what base.txt and the Host's wheels install.

    python catalog.py base ROOT       base.txt pinned to uv.lock with its hashes; needs only the
                                      standard library, so it runs before anything is installed
    python catalog.py sdists ROOT     NAME URL SHA256 of each source this build turns into a wheel
    python catalog.py write ROOT WHEELS OUT --version V --glibc G [--cpu NAME=FLAG,FLAG ...]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path

PYTHON = "3.13.12"
PLATFORM = "linux-x86_64"
MAX_MANYLINUX = 28
GROUP = "setup-catalog"
HOST = "alpha-avatar-host"
TORCH = ("torch", "torchaudio")
BASE_MEMBERS = ("alpha-avatar-agents", "alpha-avatar-core", HOST)
# Replaced (torch-cpu.txt) or never installed: the GUI OpenCV, whose cv2 the headless build
# provides, and the CUDA libraries the CPU torch does not use.
LEFT_OUT = re.compile(r"opencv-python|triton|nvidia-.*")
ENVIRONMENT = {
    "implementation_name": "cpython",
    "implementation_version": PYTHON,
    "os_name": "posix",
    "platform_machine": "x86_64",
    "platform_python_implementation": "CPython",
    "platform_release": "",
    "platform_system": "Linux",
    "platform_version": "",
    "python_full_version": PYTHON,
    "python_version": "3.13",
    "sys_platform": "linux",
    "extra": "",
}
_PLATFORMS = [f"manylinux_2_{minor}_x86_64" for minor in range(MAX_MANYLINUX, 4, -1)]
_PLATFORMS += ["manylinux2014_x86_64", "manylinux2010_x86_64", "manylinux1_x86_64"]


def canonicalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def accepted_tags() -> dict[str, int]:
    """Wheel tags the target accepts, most preferred first: CPython 3.13, abi3, then pure."""
    from packaging.tags import compatible_tags, cpython_tags

    accepted = [
        *cpython_tags((3, 13), ["cp313"], _PLATFORMS),
        *compatible_tags((3, 13), "cp313", _PLATFORMS),
    ]
    return {str(tag): rank for rank, tag in enumerate(accepted)}


class Lock:
    def __init__(self, root: Path) -> None:
        self.packages: dict[tuple[str, str], dict] = {}
        for package in tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))["package"]:
            # Workspace members have no version here: theirs is in their wheels.
            self.packages[canonicalize_name(package["name"]), package.get("version")] = package

    def find(self, dependency: dict) -> dict:
        name = canonicalize_name(dependency["name"])
        found = [
            package
            for (other, version), package in self.packages.items()
            if other == name and dependency.get("version", version) == version
        ]
        if len(found) != 1:
            sys.exit(f"uv.lock holds {len(found)} matches for {dependency}")
        return found[0]

    def closure(self, name: str, extras: tuple[str, ...] = ()) -> dict[str, dict]:
        """The distributions one requirement installs on the target, by canonical name."""
        from packaging.markers import Marker

        found: dict[str, dict] = {}
        pending = [({"name": name}, set(extras))]
        walked: set[tuple[str, str]] = set()
        while pending:
            dependency, wanted = pending.pop()
            package = self.find(dependency)
            key = canonicalize_name(package["name"])
            if LEFT_OUT.fullmatch(key):
                continue
            found[key] = package
            for extra in ("", *sorted(wanted)):
                if (key, extra) in walked:
                    continue
                walked.add((key, extra))
                listed = package.get("optional-dependencies", {}) if extra else {"": None}
                if extra and extra not in listed:
                    sys.exit(f"{key} has no extra {extra!r}")
                items = package.get("dependencies", []) if not extra else listed[extra]
                for item in items:
                    if "marker" in item and not Marker(item["marker"]).evaluate(ENVIRONMENT):
                        continue
                    pending.append((item, set(item.get("extra", ()))))
        return found


def roots(root: Path) -> list:
    from packaging.requirements import Requirement

    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    return [Requirement(text) for text in pyproject["dependency-groups"][GROUP]]


def base_names(root: Path) -> list[str]:
    lines = (root / "packaging" / "linux" / "base.txt").read_text(encoding="utf-8").splitlines()
    return sorted(canonicalize_name(line) for line in lines if line and not line.startswith("#"))


def requirement_keys(lock: Lock, root: Path) -> dict[str, dict[str, dict]]:
    """Each requirement setup may ask for: a distribution alone, or with one of its extras."""
    keys = {HOST: lock.closure(HOST)}
    for requirement in roots(root):
        name = canonicalize_name(requirement.name)
        keys[name] = lock.closure(name)
        for extra in requirement.extras:
            keys[f"{name}[{canonicalize_name(extra)}]"] = lock.closure(name, (extra,))
    return dict(sorted(keys.items()))


def wheel(package: dict) -> dict | None:
    """The lock's best wheel for the target, or None."""
    from packaging.utils import parse_wheel_filename

    accepted, ranked = accepted_tags(), []
    for item in package.get("wheels", ()):
        filename = item["url"].rsplit("/", 1)[-1]
        tags = parse_wheel_filename(filename)[3]
        rank = min((accepted[str(tag)] for tag in tags if str(tag) in accepted), default=None)
        if rank is not None:
            ranked.append((rank, filename, item))
    if not ranked:
        return None
    _, filename, item = min(ranked, key=lambda entry: entry[:2])
    return {
        "file": urllib.parse.unquote(filename),
        "sha256": item["hash"].removeprefix("sha256:"),
        "size": item["size"],
        "url": item["url"],
    }


def glibc(filename: str, built: str) -> str | None:
    """The oldest glibc a wheel runs on: from its manylinux tags, or this build's for its own."""
    from packaging.utils import parse_wheel_filename

    tags = parse_wheel_filename(filename)[3]
    if any(tag.platform == "any" for tag in tags):
        return None
    legacy = {"manylinux2014": (2, 17), "manylinux2010": (2, 12), "manylinux1": (2, 5)}
    floors = []
    for tag in tags:
        if found := re.match(r"manylinux_(\d+)_(\d+)_", tag.platform):
            floors.append((int(found[1]), int(found[2])))
        floors += [floor for name, floor in legacy.items() if tag.platform == f"{name}_x86_64"]
    return ".".join(map(str, min(floors))) if floors else built


def torch_pins(root: Path) -> dict[str, dict]:
    text = (root / "packaging" / "linux" / "torch-cpu.txt").read_text(encoding="utf-8")
    pins = {}
    for name, url, digest in re.findall(r"^(\S+) @ (\S+)\s*\\\s*--hash=sha256:(\w+)", text, re.M):
        request = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(request, timeout=60) as response:
            size = int(response.headers["Content-Length"])
        pins[canonicalize_name(name)] = {
            "file": urllib.parse.unquote(url.rsplit("/", 1)[-1]),
            "sha256": digest,
            "size": size,
            "url": url,
        }
    return pins


def sdists(root: Path) -> list[str]:
    """Distributions setup may install that only uv.lock's sources provide: NAME URL SHA256."""
    lock = Lock(root)
    needed: dict[str, dict] = {}
    for closure in requirement_keys(lock, root).values():
        needed |= closure
    base = set(base_names(root))
    return [
        f"{name} {package['sdist']['url']} {package['sdist']['hash'].removeprefix('sha256:')}"
        for name, package in sorted(needed.items())
        if "registry" in package["source"]
        and name not in base
        and name not in TORCH
        and wheel(package) is None
    ]


def base_requirements(root: Path) -> str:
    """base.txt pinned to uv.lock with every hash it records, for `--require-hashes`."""
    lock = Lock(root)
    lines = []
    for name in base_names(root):
        # `write` checks that the Host requires each of them.
        package = lock.find({"name": name})
        hashes = [item["hash"] for item in (*package.get("wheels", ()), package.get("sdist") or {})]
        lines.append(
            f"{name}=={package['version']} "
            + " ".join(f"--hash={digest}" for digest in hashes if digest)
        )
    return "\n".join(lines) + "\n"


def write(root: Path, wheels: Path, args: argparse.Namespace) -> dict:
    from packaging.utils import parse_wheel_filename

    lock = Lock(root)
    keys = requirement_keys(lock, root)
    built = {}
    for path in sorted(wheels.glob("*.whl")):
        name, version, *_ = parse_wheel_filename(path.name)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        built[canonicalize_name(name)] = {
            "version": str(version),
            "file": path.name,
            "sha256": digest,
            "size": path.stat().st_size,
            "url": None,  # Beside the base package: its release, or setup --artifacts.
        }
    torch = torch_pins(root)
    cpu = dict(item.split("=", 1) for item in args.cpu)
    base = sorted({*base_names(root), *map(canonicalize_name, BASE_MEMBERS)})
    distributions = {}
    for closure in keys.values():
        for name, package in closure.items():
            if name in distributions:
                continue
            if name in base:
                # Installed with the base package: no plan downloads it.
                distributions[name] = {"version": package.get("version") or built[name]["version"]}
                continue
            if name in torch:
                version = parse_wheel_filename(torch[name]["file"])[1]
                if version.public != package["version"]:
                    sys.exit(
                        f"torch-cpu.txt has {name} {version}; uv.lock has {package['version']}"
                    )
                artifact = {"version": str(version), **torch[name]}
            elif name in built:
                artifact = dict(built[name])
                if package.get("version") not in (None, artifact["version"]):
                    sys.exit(f"{artifact['file']} is not uv.lock's {name} {package['version']}")
            elif (found := wheel(package)) is not None:
                artifact = {"version": package["version"], **found}
            else:
                sys.exit(f"{name} {package['version']} has no wheel for {PLATFORM}; build one")
            artifact["glibc"] = glibc(artifact["file"], args.glibc)
            artifact["cpu"] = sorted(cpu.get(name, "").split(",")) if cpu.get(name) else []
            distributions[name] = artifact
    for name in base:
        if name not in keys[HOST]:
            sys.exit(f"The base holds {name}, which the Host does not require")
    return {
        "format": 1,
        "version": args.version,
        "platform": PLATFORM,
        "python": PYTHON,
        "base": base,
        "requirements": {key: sorted(closure) for key, closure in keys.items()},
        "distributions": dict(sorted(distributions.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sdists").add_argument("root", type=Path)
    commands.add_parser("base").add_argument("root", type=Path)
    writing = commands.add_parser("write")
    writing.add_argument("root", type=Path)
    writing.add_argument("wheels", type=Path)
    writing.add_argument("output", type=Path)
    writing.add_argument("--version", required=True)
    writing.add_argument("--glibc", required=True, help="This build's own native wheels' floor")
    writing.add_argument("--cpu", nargs="*", default=[], metavar="NAME=FLAG,FLAG")
    args = parser.parse_args()
    if args.command == "sdists":
        print("\n".join(sdists(args.root)))
    elif args.command == "base":
        sys.stdout.write(base_requirements(args.root))
    else:
        catalog = write(args.root, args.wheels, args)
        args.output.write_text(json.dumps(catalog, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
