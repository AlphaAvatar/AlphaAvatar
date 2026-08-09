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
from ..maintenance import AddOnlyStrategy, LLMJudgeStrategy, MaintenanceStrategy
from .config import MaintenanceConfig


def build_maintenance_strategy(
    config: MaintenanceConfig,
    *,
    candidate_search,
    judge,
    rewriter,
) -> MaintenanceStrategy:
    """Assemble the maintenance strategy declared by config.maintenance.ops."""
    if not config.uses_llm:
        return AddOnlyStrategy()

    return LLMJudgeStrategy(
        candidate_search=candidate_search,
        judge=judge,
        rewriter=rewriter,
        threshold=config.similarity_threshold,
        max_candidates=config.max_candidates_per_note,
        allow_update=config.allow_update,
    )
