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
"""config check names what each selection needs and lacks, by the setting that selects it."""

from __future__ import annotations

from importlib import metadata
from pathlib import Path
from unittest import mock

import pytest

# Imported at collection: the persona plugin's OpenCV adjusts process variables (O-2).
import alphaavatar.plugins.persona  # noqa: F401
from alphaavatar.host.cli.app import main

FACE = (
    "persona.plugin (runner alphaavatar.persona.face.analysis): "
    "alpha-avatar-plugins-persona[face]: insightface is not installed"
)


def check(capsys: pytest.CaptureFixture, *overrides: str) -> tuple[int, str]:
    code = main(["config", "check", *overrides])
    output = capsys.readouterr()
    return code, output.out + output.err


def test_each_selection_is_checked_against_what_is_installed(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    assert main(["config", "init", "alpha", "--avatar-id", "alpha"]) == 0
    capsys.readouterr()
    real = metadata.distribution

    def without_insightface(name: str) -> metadata.Distribution:
        if name.lower() == "insightface":
            raise metadata.PackageNotFoundError(name)
        return real(name)

    with mock.patch.object(metadata, "distribution", without_insightface):
        code, output = check(capsys)
        assert code == 2 and FACE in output and "`alphaavatar setup` installs them" in output
        # The runner that needs it is not planned once its processor is off.
        assert check(capsys, "persona.init_config.face.enabled=false")[0] == 0

    # A factory nothing registers, and an entry point nothing installs, by their settings.
    code, output = check(capsys, "persona.plugin=custom")
    assert code == 2
    assert "persona.plugin: no avatar.perception.persona factory 'custom' is registered" in output
    code, output = check(capsys, "loop.plugin=nowhere")
    assert (
        code == 2 and "loop.plugin: 0 installed alphaavatar.loop plugins named 'nowhere'" in output
    )
