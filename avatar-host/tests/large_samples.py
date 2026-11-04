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
"""Large test samples: in a Hugging Face Dataset, fetched by manifest only when a test asks.

``fixtures/large_samples.json`` names the repo, the commit every file is pinned to, the
license, and each sample's path, SHA-256 and size. Small samples are not here: test-only ones
live in their package's ``tests/fixtures/``, Doctor's own ship in the Host package. A test
marked ``@pytest.mark.large_samples("name", ...)`` gets them through the ``large_sample``
fixture; the default run deselects such tests, so ordinary CI and Doctor stay offline.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from pathlib import Path

MANIFEST = Path(__file__).parent / "fixtures" / "large_samples.json"
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class LargeSampleError(Exception):
    """Which sample could not be had, and why."""


def cache_root() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "alphaavatar" / "test-samples"


def _download(repo_id: str, repo_type: str, revision: str, path: str, root: Path) -> None:
    from huggingface_hub import hf_hub_download

    hf_hub_download(repo_id, path, repo_type=repo_type, revision=revision, local_dir=root)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(
    name: str,
    *,
    manifest: Path = MANIFEST,
    cache: Path | None = None,
    download: Callable[[str, str, str, str, Path], None] = _download,
) -> Path:
    """The sample's local file: a valid cached copy as it is, else downloaded and checked."""
    data = json.loads(manifest.read_text(encoding="utf-8"))
    entry = data["samples"].get(name)
    repo, revision = data["repo_id"], data["revision"]
    if entry is None:
        raise LargeSampleError(f"{name}: not in {manifest.name}")
    expected = entry["sha256"]
    if (
        not data["published"]
        or not _COMMIT.match(revision or "")
        or not _SHA256.match(expected or "")
    ):
        raise LargeSampleError(
            f"{name}: {repo} is not published with a pinned revision and SHA-256"
        )
    root = (cache or cache_root()) / repo / revision
    target = root / entry["path"]
    if target.is_file() and _sha256(target) == expected:
        return target  # Valid in the cache: no network at all.
    try:
        download(repo, data["repo_type"], revision, entry["path"], root)
    except Exception as error:
        raise LargeSampleError(
            f"{name}: download of {entry['path']} from {repo}@{revision[:12]} failed: "
            f"{type(error).__name__}"
        ) from None
    found = _sha256(target) if target.is_file() else "nothing"
    if found != expected:
        target.unlink(missing_ok=True)
        raise LargeSampleError(
            f"{name}: SHA-256 mismatch for {entry['path']}: expected {expected[:12]}, "
            f"got {found[:12]}"
        )
    return target
