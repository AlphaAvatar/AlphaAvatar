# Copyright 2025 AlphaAvatar project
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

SESSION_GATE_FRAGMENT = """
----------------------------------------------------------------------
SESSION VALUE GATE
----------------------------------------------------------------------

Before writing anything, decide whether this session contains information
worth remembering beyond this conversation.

If it does NOT, return empty user_or_tool_memory_entries and empty
assistant_memory_entries. Do not invent content to fill the fields.

A session is NOT worth remembering when it contains only:
- greetings, small talk, or acknowledgements
- one-off factual answers with no likely follow-up value
- requests that were fully satisfied and leave no continuing direction
""".strip()
