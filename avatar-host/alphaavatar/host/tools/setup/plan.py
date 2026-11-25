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
"""An install plan: the artifacts some requirements need on one platform, from its catalog.

A catalog belongs to one AlphaAvatar version and platform (packaging/linux/catalog.py builds
Linux's). It maps each requirement to the distributions it needs, and each distribution to one
artifact with its SHA-256 and size. The plan is everything the requirements need beyond the
base the catalog shipped with; the same catalog, base and requirements always give the same
plan and identifier. Model weights are not artifacts: runners fetch them into the model cache.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

FORMAT = 1


class PlanError(ValueError):
    """A requirement or artifact this catalog cannot provide; safe to show."""


@dataclass(frozen=True, slots=True)
class Artifact:
    name: str
    version: str
    file: str
    sha256: str
    size: int
    url: str | None  # None: published beside the base package, by its release.
    glibc: str | None = None  # The oldest glibc its native code runs on; None: pure Python.
    cpu: tuple[str, ...] = ()  # CPU flags its native code needs.


@dataclass(frozen=True, slots=True)
class Plan:
    version: str
    platform: str
    base: str  # The base package's identifier, which the artifacts complete.
    requirements: tuple[str, ...]
    artifacts: tuple[Artifact, ...]

    def document(self) -> dict[str, Any]:
        return {
            "format": FORMAT,
            "version": self.version,
            "platform": self.platform,
            "base": self.base,
            "requirements": list(self.requirements),
            "artifacts": [
                asdict(artifact) | {"cpu": list(artifact.cpu)} for artifact in self.artifacts
            ],
        }

    @property
    def id(self) -> str:
        text = json.dumps(self.document(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode()).hexdigest()

    @property
    def download_bytes(self) -> int:
        return sum(artifact.size for artifact in self.artifacts)

    @property
    def glibc(self) -> str | None:
        floors = [a.glibc for a in self.artifacts if a.glibc is not None]
        return max(floors, key=lambda floor: tuple(map(int, floor.split(".")))) if floors else None

    @property
    def cpu(self) -> tuple[str, ...]:
        return tuple(sorted({flag for artifact in self.artifacts for flag in artifact.cpu}))


def check_catalog(catalog: Any) -> dict[str, Any]:
    if not isinstance(catalog, dict) or catalog.get("format") != FORMAT:
        raise PlanError(f"Not a format {FORMAT} AlphaAvatar catalog")
    for key in ("version", "platform", "base", "requirements", "distributions"):
        if key not in catalog:
            raise PlanError(f"The catalog has no {key}")
    return catalog


def plan_install(catalog: dict[str, Any], requirements: Iterable[str], *, base: str) -> Plan:
    """The artifacts the requirements need beyond the base, sorted by distribution."""
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name

    catalog = check_catalog(catalog)
    requirements = tuple(sorted(dict.fromkeys(requirements)))
    needed: set[str] = set()
    for text in requirements:
        requirement = Requirement(text)
        name = canonicalize_name(requirement.name)
        keys = [name, *(f"{name}[{canonicalize_name(extra)}]" for extra in requirement.extras)]
        for key in keys:
            if key not in catalog["requirements"]:
                raise PlanError(f"{text}: {key} is not in this package's catalog")
            needed.update(catalog["requirements"][key])
    artifacts = []
    for name in sorted(needed - set(catalog["base"])):
        entry = catalog["distributions"][name]
        try:
            artifacts.append(
                Artifact(
                    name=name,
                    version=entry["version"],
                    file=entry["file"],
                    sha256=entry["sha256"],
                    size=int(entry["size"]),
                    url=entry["url"],
                    glibc=entry.get("glibc"),
                    cpu=tuple(entry.get("cpu", ())),
                )
            )
        except KeyError as error:
            raise PlanError(f"The catalog's {name} has no {error.args[0]}") from None
        if "/" in entry["file"] or entry["file"] in ("", ".", ".."):
            raise PlanError(f"The catalog's {name} names an unsafe file")
    return Plan(catalog["version"], catalog["platform"], base, requirements, tuple(artifacts))
