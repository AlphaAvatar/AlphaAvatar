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
"""Stored credentials: private, exact, never over the environment, and committed with the
default bundle by one settings replacement."""

from __future__ import annotations

import os
import signal
import stat
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from alphaavatar.host.configs.bundles import ConfigReferenceError, read_settings
from alphaavatar.host.configs.credentials import (
    credentials_path,
    load_credentials,
    stored_credentials,
)
from alphaavatar.host.configs.template import create_bundle
from alphaavatar.host.workspace import ApplicationPaths

# Quotes, backslashes, dollar interpolation and spaces survive as written.
AWKWARD = "sk-\"quoted\"\\path ${HOME} $OTHER 'single' end"


def stored(paths: ApplicationPaths) -> list[str]:
    return sorted(path.name for path in paths.settings_dir.glob("credentials-*.env"))


def test_credentials_are_private_exact_and_never_override_the_environment(tmp_path: Path) -> None:
    paths = ApplicationPaths.from_root(tmp_path / "home")
    first = {"OPENAI_API_KEY": AWKWARD, "LIVEKIT_URL": "wss://a.invalid"}
    create_bundle(paths, "alpha", avatar_id="alpha", make_default=True, credentials=first)
    path = credentials_path(paths)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert read_settings(paths) == {"default_bundle": "alpha", "credentials": path.name}
    with mock.patch.dict(os.environ, {"LIVEKIT_URL": "wss://set.invalid"}):
        os.environ.pop("OPENAI_API_KEY", None)
        assert load_credentials(paths) == ("OPENAI_API_KEY",)
        assert os.environ["OPENAI_API_KEY"] == AWKWARD
        assert os.environ["LIVEKIT_URL"] == "wss://set.invalid"  # Set already: kept.

    # A later bundle keeps the other names, in a new file; the one it replaced is gone.
    second = {"QDRANT_URL": "http://q.invalid", "LIVEKIT_URL": "wss://b"}
    create_bundle(paths, "beta", avatar_id="beta", make_default=True, credentials=second)
    assert stored_credentials(paths) == first | second
    assert stored(paths) == [credentials_path(paths).name] != [path.name]
    # Without credentials to store, the stored ones stay as named.
    create_bundle(paths, "gamma", avatar_id="gamma", make_default=True)
    assert stored_credentials(paths) == first | second


@pytest.mark.parametrize(
    "values", [{"lower_case": "x"}, {"OPENAI_API_KEY": ""}, {"OPENAI_API_KEY": "a\nB=c"}]
)
def test_unsafe_credentials_are_refused_before_anything_changes(
    tmp_path: Path, values: dict[str, str]
) -> None:
    paths = ApplicationPaths.from_root(tmp_path / "home")
    kept = {"LIVEKIT_URL": "wss://a.invalid"}
    create_bundle(paths, "alpha", avatar_id="alpha", make_default=True, credentials=kept)
    settings, files = read_settings(paths), stored(paths)
    with pytest.raises(ValueError):
        create_bundle(paths, "beta", avatar_id="beta", make_default=True, credentials=values)
    assert (read_settings(paths), stored(paths)) == (settings, files)
    assert stored_credentials(paths) == kept
    assert not (paths.configs.bundles_dir / "beta.yaml").exists()


KILLED = """
import os, signal, sys
from alphaavatar.host.configs.template import create_bundle
from alphaavatar.host.workspace import ApplicationPaths

replace = os.replace

def killed(source, target):
    if os.path.basename(target) == "settings.yaml":
        os.kill(os.getpid(), signal.SIGKILL)  # Nothing runs after this, not even cleanup.
    return replace(source, target)

os.replace = killed
paths = ApplicationPaths.from_root(sys.argv[1])
create_bundle(paths, "beta", avatar_id="beta", make_default=True, credentials={"OPENAI_API_KEY": "new"})
"""


def test_a_kill_before_the_settings_replacement_leaves_every_bundle_reading_what_it_read(
    tmp_path: Path,
) -> None:
    paths = ApplicationPaths.from_root(tmp_path / "home")
    old = {"OPENAI_API_KEY": "old", "LIVEKIT_URL": "wss://a.invalid"}
    create_bundle(paths, "alpha", avatar_id="alpha", make_default=True, credentials=old)
    settings = read_settings(paths)
    killed = subprocess.run([sys.executable, "-c", KILLED, str(paths.root)], timeout=60)
    assert killed.returncode == -signal.SIGKILL
    # The new credentials were written, and nothing names them: the old default reads the old.
    assert len(stored(paths)) == 2
    assert read_settings(paths) == settings and stored_credentials(paths) == old
    # The next store, under the same lock, removes what the killed run wrote.
    create_bundle(paths, "gamma", avatar_id="gamma", make_default=True, credentials={"X": "1"})
    assert stored(paths) == [credentials_path(paths).name]
    assert stored_credentials(paths) == old | {"X": "1"}


@pytest.mark.parametrize("settings", ["default_bundle: [\n", "credentials: ../outside.env\n"])
def test_settings_that_name_no_stored_file_load_none_and_setup_refuses_them(
    tmp_path: Path, settings: str
) -> None:
    paths = ApplicationPaths.from_root(tmp_path / "home")
    create_bundle(paths, "alpha", avatar_id="alpha", make_default=True, credentials={"A": "1"})
    (paths.root / "outside.env").write_text('A="outside"\n')
    paths.settings_file.write_text(settings)
    # Loading reads no stored value, from settings' directory or beyond; storing refuses.
    with mock.patch.dict(os.environ, clear=True):
        assert load_credentials(paths) == () and "A" not in os.environ
    with pytest.raises(ConfigReferenceError):
        stored_credentials(paths)
