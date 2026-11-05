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
"""Agents declares exactly what its own code imports; a plugin's libraries are the plugin's."""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
# Import names of Agents' requirements, and of what they bring with them.
DISTRIBUTIONS = {
    "dotenv": "python-dotenv",
    "filelock": "filelock",
    "huggingface_hub": "huggingface-hub",
    "jsonschema": "jsonschema",
    "lancedb": "lancedb",
    "numpy": "numpy",
    "pydantic": "pydantic",
    "pydantic_core": "pydantic",  # Pinned by pydantic itself.
    "qdrant_client": "qdrant-client",
    "referencing": "referencing",
    "slugify": "python-slugify",
}
# Probed inside a function, where its absence is an answer: gpu_available() without torch.
PROBES = {"torch"}


def imports() -> tuple[set[str], set[str]]:
    """Third-party modules Agents imports at module level, and inside functions."""
    eager: set[str] = set()
    lazy: set[str] = set()

    def visit(node: ast.AST, deferred: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.If) and "TYPE_CHECKING" in ast.unparse(child.test):
                continue
            if isinstance(child, ast.Import | ast.ImportFrom):
                names = (
                    [alias.name for alias in child.names]
                    if isinstance(child, ast.Import)
                    else ([child.module] if child.module and not child.level else [])
                )
                for name in names:
                    top = name.split(".")[0]
                    if top not in sys.stdlib_module_names and top != "alphaavatar":
                        (lazy if deferred else eager).add(top)
            function = isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
            visit(child, deferred or function)

    for path in (ROOT / "alphaavatar").rglob("*.py"):
        visit(ast.parse(path.read_text(encoding="utf-8")), False)
    return eager, lazy


def test_agents_declares_exactly_what_its_code_imports() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    declared = {canonicalize_name(Requirement(text).name) for text in project["dependencies"]}
    extras = {
        canonicalize_name(Requirement(text).name)
        for texts in project["optional-dependencies"].values()
        for text in texts
    }
    eager, lazy = imports()
    unknown = (eager | lazy) - DISTRIBUTIONS.keys() - PROBES
    assert not unknown, f"Map these imports to their distributions: {sorted(unknown)}"
    # Loaded with Agents: required. Loaded on use: required or an extra's.
    assert {DISTRIBUTIONS[name] for name in eager} <= declared
    assert {DISTRIBUTIONS[name] for name in lazy - PROBES} <= declared | extras
    # Nothing declared for another package's code: each requirement is Agents' own.
    used = {DISTRIBUTIONS[name] for name in (eager | lazy) - PROBES}
    assert declared - {"alpha-avatar-core"} == used & declared
