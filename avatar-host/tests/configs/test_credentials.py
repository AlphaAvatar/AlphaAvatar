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
"""Stored credentials: private, exact, never over the environment, and undone as a whole."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest import mock

import pytest

from alphaavatar.host.configs.credentials import (
    credentials_path,
    load_credentials,
    store_credentials,
)
from alphaavatar.host.workspace import ApplicationPaths

# Quotes, backslashes, dollar interpolation and spaces survive as written.
AWKWARD = "sk-\"quoted\"\\path ${HOME} $OTHER 'single' end"


def test_credentials_are_private_exact_and_never_override_the_environment(tmp_path: Path) -> None:
    paths = ApplicationPaths.from_root(tmp_path / "home")
    undo = store_credentials(paths, {"OPENAI_API_KEY": AWKWARD, "LIVEKIT_URL": "wss://a.invalid"})
    path = credentials_path(paths)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with mock.patch.dict(os.environ, {"LIVEKIT_URL": "wss://set.invalid"}):
        os.environ.pop("OPENAI_API_KEY", None)
        assert load_credentials(paths) == ("OPENAI_API_KEY",)
        assert os.environ["OPENAI_API_KEY"] == AWKWARD
        assert os.environ["LIVEKIT_URL"] == "wss://set.invalid"  # Set already: kept.

    # A later store keeps the other names; its undo puts back the file as it was.
    before = path.read_bytes()
    second = store_credentials(paths, {"QDRANT_URL": "http://q.invalid", "LIVEKIT_URL": "wss://b"})
    with mock.patch.dict(os.environ, clear=True):
        load_credentials(paths)
        assert os.environ["OPENAI_API_KEY"] == AWKWARD
        assert (os.environ["LIVEKIT_URL"], os.environ["QDRANT_URL"]) == (
            "wss://b",
            "http://q.invalid",
        )
    second()
    assert path.read_bytes() == before
    undo()
    assert not path.exists()
    assert sorted(item.name for item in path.parent.iterdir()) == []


@pytest.mark.parametrize(
    "values", [{"lower_case": "x"}, {"OPENAI_API_KEY": ""}, {"OPENAI_API_KEY": "a\nB=c"}]
)
def test_unsafe_credentials_are_refused_before_the_file_changes(
    tmp_path: Path, values: dict[str, str]
) -> None:
    paths = ApplicationPaths.from_root(tmp_path / "home")
    store_credentials(paths, {"LIVEKIT_URL": "wss://a.invalid"})
    before = credentials_path(paths).read_bytes()
    with pytest.raises(ValueError):
        store_credentials(paths, values)
    assert credentials_path(paths).read_bytes() == before
