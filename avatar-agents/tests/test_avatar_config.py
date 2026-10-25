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
"""Avatar identity contract; this does not claim configuration validation is side-effect free."""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest
from pydantic import ValidationError

# Imported at collection: the configuration package eagerly loads plugins and third-party
# libraries that adjust process variables while importing.
from alphaavatar.agents.configs import AvatarConfig

# KD-2: Memory/Persona defaults still publish these even when the configuration is rejected.
KD2_VARIABLES = {"MEMORY_VDB_CONFIG", "MEMORY_VDB_TYPE", "PERSONA_VDB_CONFIG", "PERSONA_VDB_TYPE"}


@pytest.mark.parametrize(
    ("value", "location"),
    [({}, ("avatar",)), ({"avatar": {"name": "Assistant"}}, ("avatar", "id"))],
    ids=["missing-avatar", "missing-id"],
)
def test_missing_avatar_identity_is_rejected_instead_of_generated(
    value: dict[str, object], location: tuple[str, ...], tmp_path: Path
) -> None:
    before = dict(os.environ)
    with mock.patch.dict(os.environ):
        with pytest.raises(ValidationError) as rejected:
            AvatarConfig.model_validate(value)
        changed = {key for key, _ in before.items() ^ os.environ.items()}
    assert [(error["loc"], error["type"]) for error in rejected.value.errors()] == [
        (location, "missing")
    ]
    # Only the known KD-2 leak is contained; a rejected identity publishes no workspace state.
    assert changed <= KD2_VARIABLES
    assert not any((tmp_path / "home").iterdir())
