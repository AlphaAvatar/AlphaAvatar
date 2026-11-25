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
"""Large samples by manifest: pinned, checked, reused from the cache, failures by name."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from large_samples import MANIFEST, LargeSampleError, fetch

REVISION = "0123456789abcdef0123456789abcdef01234567"


def test_the_manifest_names_each_sample_and_whether_it_is_published() -> None:
    data = json.loads(MANIFEST.read_text())
    assert (data["repo_id"], data["repo_type"]) == ("AlphaAvatar/diagnostics-fixtures", "dataset")
    assert all(entry["path"] and entry["use"] for entry in data["samples"].values())
    if data["published"]:
        assert len(data["revision"]) == 40 and data["license"]
        assert all(len(e["sha256"]) == 64 and e["bytes"] for e in data["samples"].values())
        return
    # Not published yet: asking for a sample says so, by name, and reaches no network.
    for name in data["samples"]:
        with pytest.raises(LargeSampleError, match=f"^{name}: .* is not published"):
            fetch(name)


def test_a_valid_cached_copy_is_used_and_anything_else_is_fetched_and_checked(
    tmp_path: Path,
) -> None:
    content = b"sixteen kilohertz"
    manifest = tmp_path / "large_samples.json"
    manifest.write_text(
        json.dumps(
            {
                "repo_id": "AlphaAvatar/diagnostics-fixtures",
                "repo_type": "dataset",
                "revision": REVISION,
                "license": "cc-by-4.0",
                "published": True,
                "samples": {
                    "long_session": {
                        "path": "speech/long.wav",
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "bytes": len(content),
                        "use": "a test",
                    }
                },
            }
        )
    )
    cache = tmp_path / "cache"
    target = cache / "AlphaAvatar/diagnostics-fixtures" / REVISION / "speech/long.wav"
    calls: list[tuple[str, ...]] = []

    def writes(data: bytes):
        def download(repo: str, kind: str, revision: str, path: str, root: Path) -> None:
            calls.append((repo, kind, revision, path))
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_bytes(data)

        return download

    def refused(*args: object) -> None:
        raise OSError("unreachable")

    # Downloaded at the pinned commit, then a valid cached copy needs no download at all.
    assert fetch("long_session", manifest=manifest, cache=cache, download=writes(content)) == target
    assert calls == [("AlphaAvatar/diagnostics-fixtures", "dataset", REVISION, "speech/long.wav")]
    assert fetch("long_session", manifest=manifest, cache=cache, download=refused) == target
    # A damaged copy is fetched again; a download that does not match is named and removed.
    target.write_bytes(b"damaged")
    assert fetch("long_session", manifest=manifest, cache=cache, download=writes(content)) == target
    target.write_bytes(b"damaged")
    with pytest.raises(LargeSampleError, match=r"^long_session: SHA-256 mismatch for speech/long"):
        fetch("long_session", manifest=manifest, cache=cache, download=writes(b"other"))
    assert not target.exists()
    with pytest.raises(LargeSampleError) as failed:
        fetch("long_session", manifest=manifest, cache=cache, download=refused)
    assert str(failed.value) == (
        "long_session: download of speech/long.wav from "
        f"AlphaAvatar/diagnostics-fixtures@{REVISION[:12]} failed: OSError"
    )
    with pytest.raises(LargeSampleError, match="^short: not in large_samples.json"):
        fetch("short", manifest=manifest, cache=cache, download=refused)
