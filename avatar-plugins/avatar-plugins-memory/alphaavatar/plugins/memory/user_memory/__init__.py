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
from .consolidator import NoteConsolidator
from .notes import apply_assignments, build_note, rewrite_note
from .prompts import CONSOLIDATE_NOTES_PROMPT, SESSION_SUMMARY_PROMPT
from .schema import NEW_NOTE_PREFIX, NoteAssignment, NoteConsolidation, NoteDraft

__all__ = [
    "CONSOLIDATE_NOTES_PROMPT",
    "NEW_NOTE_PREFIX",
    "SESSION_SUMMARY_PROMPT",
    "NoteAssignment",
    "NoteConsolidation",
    "NoteConsolidator",
    "NoteDraft",
    "apply_assignments",
    "build_note",
    "rewrite_note",
]
