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

import argparse
import ast
import re
import sys
import tomllib
from graphlib import CycleError, TopologicalSorter
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parents[1]
PYTHON_RANGE = SpecifierSet(">=3.13,<3.14")
FORBIDDEN = {"livekit-agents", "livekit-plugins-openai"}


def read_toml(path: Path) -> dict:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def members(root: Path, config: dict) -> list[Path]:
    workspace = config["tool"]["uv"]["workspace"]
    included = {path for pattern in workspace["members"] for path in root.glob(pattern)}
    excluded = {path for pattern in workspace.get("exclude", []) for path in root.glob(pattern)}
    return sorted(included - excluded)


def check(root: Path, *, metadata_only: bool = False) -> tuple[list[str], int]:
    errors: list[str] = []
    config = read_toml(root / "pyproject.toml")
    packages: dict[str, tuple[Path, dict]] = {}
    graph: dict[str, set[str]] = {}

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    def python_range(value: str, label: str) -> None:
        try:
            accepted = (PYTHON_RANGE, SpecifierSet("==3.13.*"))
            require(SpecifierSet(value) in accepted, f"{label}: expected {PYTHON_RANGE}")
        except InvalidSpecifier:
            errors.append(f"{label}: invalid Python requirement")

    def requirements(values: list, label: str) -> list[Requirement]:
        parsed: list[Requirement] = []
        names: set[str] = set()
        for value in values:
            try:
                item = Requirement(value)
            except (InvalidRequirement, TypeError):
                errors.append(f"{label}: invalid dependency declaration")
                continue
            name = canonicalize_name(item.name)
            require(name not in names, f"{label}: duplicate dependency {name}")
            require(name not in FORBIDDEN, f"{label}: forbidden SDK dependency {name}")
            names.add(name)
            parsed.append(item)
        return parsed

    require(
        (root / ".python-version").read_text().strip() == "3.13", ".python-version: expected 3.13"
    )
    paths = members(root, config)
    require(bool(paths), "No workspace members were found")
    for directory in paths:
        label = str(directory.relative_to(root))
        manifest = directory / "pyproject.toml"
        if not manifest.is_file():
            errors.append(f"{label}: missing pyproject.toml")
            continue
        data = read_toml(manifest)
        project = data["project"]
        name = canonicalize_name(project["name"])
        require(name not in packages, f"{label}: duplicate project name {name}")
        packages[name] = (directory, data)
        graph[name] = set()
        python_range(project.get("requires-python", ""), f"{label}: requires-python")
        versions = {
            item
            for item in project.get("classifiers", [])
            if re.fullmatch(r"Programming Language :: Python :: 3\.\d+", item)
        }
        require(
            versions == {"Programming Language :: Python :: 3.13"}, f"{label}: Python classifiers"
        )
        require(project.get("license") == "Apache-2.0", f"{label}: SPDX license expression")
        require(project.get("license-files") == ["LICENSE"], f"{label}: package-local license file")
        license_path = directory / "LICENSE"
        require(license_path.is_file(), f"{label}: missing LICENSE")
        if license_path.is_file():
            require(
                license_path.read_bytes() == (root / "LICENSE").read_bytes(),
                f"{label}: license drift",
            )
        require(project.get("dynamic") == ["version"], f"{label}: expected dynamic version")
        require(
            data["build-system"]["build-backend"] == "hatchling.build", f"{label}: build backend"
        )
        build_requirements = requirements(
            data["build-system"]["requires"], f"{label}: build requirements"
        )
        require(
            any(
                canonicalize_name(item.name) == "hatchling"
                and "1.27.0" in item.specifier
                and "1.26.0" not in item.specifier
                and "2.0.0" not in item.specifier
                for item in build_requirements
            ),
            f"{label}: Hatchling must support SPDX/license-files and exclude a new major version",
        )
        targets = data["tool"]["hatch"]["build"]["targets"]
        require(
            targets["wheel"].get("packages") == ["alphaavatar"], f"{label}: namespace packaging"
        )
        required_files = {"alphaavatar", "README.md", "pyproject.toml", "LICENSE"}
        require(
            required_files <= set(targets["sdist"]["include"]),
            f"{label}: incomplete sdist manifest",
        )
        if not metadata_only:
            relative_paths = [project["readme"], data["tool"]["hatch"]["version"]["path"]]
            for relative in relative_paths:
                target = (directory / relative).resolve()
                require(
                    target.is_relative_to(directory.resolve()), f"{label}: path escapes package"
                )
                require(target.is_file(), f"{label}: missing {relative}")
            require((directory / "alphaavatar").is_dir(), f"{label}: missing namespace source")
            require(
                not (directory / "alphaavatar/__init__.py").exists(),
                f"{label}: shared namespace initializer",
            )
            version_path = directory / relative_paths[1]
            if version_path.is_file():
                tree = ast.parse(version_path.read_text(encoding="utf-8"))
                versions_found = [
                    ast.literal_eval(node.value)
                    for node in tree.body
                    if isinstance(node, ast.Assign)
                    and any(
                        isinstance(target, ast.Name) and target.id == "__version__"
                        for target in node.targets
                    )
                ]
                try:
                    require(len(versions_found) == 1, f"{label}: expected one __version__")
                    for version in versions_found:
                        Version(version)
                except (InvalidVersion, TypeError):
                    errors.append(f"{label}: invalid package version")
            entry_tables = [project.get("scripts", {}), *project.get("entry-points", {}).values()]
            for entries in entry_tables:
                for value in entries.values():
                    module = directory / value.split(":", 1)[0].replace(".", "/")
                    require(
                        module.with_suffix(".py").is_file() or (module / "__init__.py").is_file(),
                        f"{label}: missing entrypoint module",
                    )

    sources = config["tool"]["uv"]["sources"]
    require(set(sources) == set(packages), "Workspace source names and members differ")
    for name, source in sources.items():
        require(source == {"workspace": True}, f"{name}: expected workspace source")
    for name, (_directory, data) in packages.items():
        project = data["project"]
        direct = requirements(project.get("dependencies", []), f"{name}: dependencies")
        groups = [("dependencies", direct)]
        groups.extend(
            (group, requirements(values, f"{name}: extra {group}"))
            for group, values in project.get("optional-dependencies", {}).items()
        )
        for _group, values in groups:
            for item in values:
                dependency = canonicalize_name(item.name)
                if dependency in packages:
                    graph[name].add(dependency)
                    extras = packages[dependency][1]["project"].get("optional-dependencies", {})
                    require(item.extras <= set(extras), f"{name}: unknown extra of {dependency}")
                elif dependency.startswith("alpha-avatar-"):
                    errors.append(f"{name}: unresolved workspace dependency {dependency}")
        if name.startswith("alpha-avatar-plugins-"):
            direct_names = {canonicalize_name(item.name) for item in direct}
            require(
                {"alpha-avatar-core", "alpha-avatar-agents"} <= direct_names,
                f"{name}: missing framework dependency",
            )
    try:
        TopologicalSorter(graph).prepare()
    except CycleError:
        errors.append("Workspace dependencies contain a cycle")

    dependency_groups = config["dependency-groups"]
    group_graph: dict[str, set[str]] = {}
    for group, values in dependency_groups.items():
        group_graph[group] = set()
        direct_values = []
        for value in values:
            if isinstance(value, dict):
                included = value.get("include-group")
                valid = set(value) == {"include-group"} and isinstance(included, str)
                require(valid, f"Group {group}: invalid include-group declaration")
                if valid:
                    require(included in dependency_groups, f"Group {group}: missing {included}")
                    group_graph[group].add(included)
            else:
                direct_values.append(value)
        for item in requirements(direct_values, f"Group {group}"):
            name = canonicalize_name(item.name)
            if name in packages:
                extras = packages[name][1]["project"].get("optional-dependencies", {})
                require(item.extras <= set(extras), f"Group {group}: unknown extra of {name}")
            elif name.startswith("alpha-avatar-"):
                errors.append(f"Group {group}: unresolved workspace dependency {name}")
    try:
        TopologicalSorter(group_graph).prepare()
    except CycleError:
        errors.append("Development dependency groups contain a cycle")

    ruff = config["tool"]["ruff"]
    require(ruff.get("target-version") == "py313", "Ruff target must be py313")
    require(ruff.get("unsafe-fixes") is False, "Unsafe automatic fixes must not be enabled")
    require(ruff.get("force-exclude") is True, "Explicit filenames must respect exclusions")
    require("exclude" not in ruff, "Use extend-exclude to retain Ruff's built-in exclusions")
    require(ruff.get("line-length") == 100, "Ruff line width must be 100")
    require(ruff["format"].get("skip-magic-trailing-comma") is True, "Keep compact formatting")
    require(ruff["lint"]["isort"].get("split-on-trailing-comma") is False, "Keep compact imports")
    require("TID251" in ruff["lint"]["select"], "Missing banned-import lint rule")
    require(
        "livekit.agents" in ruff["lint"]["flake8-tidy-imports"]["banned-api"], "Missing SDK ban"
    )
    lint = requirements(config["dependency-groups"]["lint"], "lint tools")
    pinned = [str(item.specifier) for item in lint if canonicalize_name(item.name) == "ruff"]
    require(pinned == [ruff.get("required-version")], "Ruff dependency and required-version differ")
    hooks = (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    pattern = (
        r"(?ms)^  - repo: https://github.com/astral-sh/ruff-pre-commit\n"
        r"(.*?)(?=^  - repo:|\Z)"
    )
    block = re.search(pattern, hooks)
    revision = re.search(r"(?m)^    rev: v([0-9.]+)\s*$", block[1]) if block else None
    require(revision is not None and pinned == [f"=={revision[1]}"], "pre-commit Ruff pin differs")
    require("--unsafe-fixes" not in hooks, "pre-commit must not enable unsafe fixes")
    require(config["tool"]["mypy"].get("python_version") == "3.13", "Mypy target must be 3.13")

    if not metadata_only:
        lock_path = root / "uv.lock"
        if not lock_path.is_file():
            errors.append("Missing uv.lock; resolve and review it before enabling the migration")
        else:
            lock = read_toml(lock_path)
            python_range(lock.get("requires-python", ""), "uv.lock: requires-python")
            require(
                set(lock.get("manifest", {}).get("members", [])) == set(packages),
                "Lock members differ",
            )
            locked_names = {canonicalize_name(item["name"]) for item in lock.get("package", [])}
            require(not (locked_names & FORBIDDEN), "Agents SDK remains in the lock")
    return errors, len(packages)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check workspace metadata without importing runtime code."
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Skip source/entrypoint and lock checks; not a release gate.",
    )
    args = parser.parse_args()
    try:
        errors, count = check(ROOT, metadata_only=args.metadata_only)
    except (OSError, KeyError, TypeError, ValueError, SyntaxError) as error:
        print(f"Workspace check could not complete: {type(error).__name__}", file=sys.stderr)
        return 2
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    suffix = (
        "metadata only; source/build/lock NOT verified"
        if args.metadata_only
        else "run uv lock --check as well"
    )
    print(f"Workspace metadata consistent: {count} members ({suffix}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
