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
from .candidates import (
    RecalledCandidateCache,
    consolidated_from_hits,
    filter_hits,
    merge_candidates,
)
from .config import (
    CandidateSource,
    ConsolidationConfig,
    ConsolidationMode,
    ExtractionConfig,
    ItemOp,
    MaintenanceConfig,
    MemoryPipelineConfig,
)
from .consolidation_op import (
    apply_assignments,
    build_consolidated_memory,
    rewrite_consolidated_memory,
)
from .consolidator import MemoryConsolidator
from .prompts import (
    CONSOLIDATION_PROMPT,
    SESSION_SUMMARY_PROMPT,
)
from .schema import (
    NEW_CONSOLIDATED_PREFIX,
    ConsolidatedMemoryDraft,
    ConsolidationPlan,
    ConsolidationResult,
    MemoryAssignment,
)

__all__ = [
    "CONSOLIDATION_PROMPT",
    "NEW_CONSOLIDATED_PREFIX",
    "SESSION_SUMMARY_PROMPT",
    "CandidateSource",
    "ConsolidatedMemoryDraft",
    "ConsolidationConfig",
    "ConsolidationMode",
    "ConsolidationPlan",
    "ConsolidationResult",
    "ExtractionConfig",
    "ItemOp",
    "MaintenanceConfig",
    "MemoryAssignment",
    "MemoryConsolidator",
    "MemoryPipelineConfig",
    "RecalledCandidateCache",
    "apply_assignments",
    "build_consolidated_memory",
    "consolidated_from_hits",
    "filter_hits",
    "merge_candidates",
    "rewrite_consolidated_memory",
]
