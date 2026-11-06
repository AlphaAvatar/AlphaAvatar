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
"""The model file resolver while downloads are off: a missing file says so by its type."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from alphaavatar.agents.utils.files.model.model_files import ModelNotCached, resolve_url_file

SHA = "0" * 64


def test_a_model_file_missing_while_downloads_are_off_is_model_not_cached(tmp_path: Path) -> None:
    with mock.patch.dict("os.environ", {"ALPHAAVATAR_MODEL_OFFLINE": "1"}):
        with pytest.raises(ModelNotCached) as raised:
            resolve_url_file(
                models_dir=tmp_path,
                namespace=("doctor",),
                filename="weights.bin",
                url="https://models.invalid/weights.bin",
                sha256=SHA,
                size=8,
            )
    # Still a missing file to callers that only know that.
    assert isinstance(raised.value, FileNotFoundError)
