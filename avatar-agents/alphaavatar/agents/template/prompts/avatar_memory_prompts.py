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
MEMORY_CONVERSATION_RETRIEVAL_PROMPT = """1) The user implicitly or explicitly refers to previous dialogue content (outside the context of the current conversation). (e.g., "as before", "same plan", "Do you remember").
2) When the user asks ASSISTANT about past experiences, behaviors, trajectories, etc. (e.g., "have you ever")."""


MEMORY_TOOLS_RETRIEVAL_PROMPT = """1) You must choose among multiple tools, or decide parameters/strategy.
2) You can reuse resource identifiers: doc/spreadsheet/dataset IDs, default calendar/mailbox, repository, environment (prod/staging).
3) You need known boundaries: rate limits, quotas, timeouts, pagination, common errors and workarounds.
4) You should apply default configs: model/temperature, retrieval top-k, region/language filters, batching policies, retry/backoff.
5) You might hit a warm cache or reuse summaries of prior tool outputs.
6) You must confirm auth/connectivity status from previous runs (status only, never secrets)."""
