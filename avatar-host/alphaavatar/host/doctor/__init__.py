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
"""Doctor: diagnosis of the installation and a selected configuration, as plain data.

``diagnose`` runs the static checks; ``diagnose_runtime`` adds the runtime checks, which run
the selected runners that offer a probe (``InferenceRunner.probe``, see ``runtime``).
"""

from .doctor import CHECKS, diagnose, diagnose_runtime, probes
from .enums import CheckStatus
from .schemas import Check, CheckSpec, Report, RunnerResult

__all__ = [
    "CHECKS",
    "Check",
    "CheckSpec",
    "CheckStatus",
    "Report",
    "RunnerResult",
    "diagnose",
    "diagnose_runtime",
    "probes",
]
