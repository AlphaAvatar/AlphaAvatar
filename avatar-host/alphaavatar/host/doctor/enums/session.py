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
from enum import StrEnum


class ScenarioOutcome(StrEnum):
    """What became of one modality scenario; only PASSED and FAILED were measured."""

    PASSED = "passed"
    FAILED = "failed"
    NOT_ENABLED = "not_enabled"  # The configuration does not select it.
    CONDITIONS_UNMET = "conditions_unmet"  # Selected, but authorization or a model is missing.
    NO_COVERAGE = "no_coverage"  # Selected, but Doctor has no way to drive or observe it yet.
    INTERRUPTED = "interrupted"
