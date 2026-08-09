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
from langchain_core.prompts import ChatPromptTemplate

# Semantics ported from UnifiedMem's memory-update agent. The temporal-evolution
# clause matters most: the same topic at a different point in time is a NEW
# memory, not an update of the old one.
JUDGE_SYSTEM = """You are an "AlphaAvatar Memory Maintenance Judge".

For each incoming memory you are given a list of existing memories that are
semantically close to it. Decide what should happen to the incoming memory.

Decisions:
- "add"    : the incoming memory carries new, distinct, or time-specific
             information. Store it as a separate memory.
- "noop"   : the incoming memory is already fully covered by an existing
             memory and adds nothing. Discard it.
- "update" : the incoming memory refines or completes one or more existing
             memories without fully overlapping them. Name their ids.

Critical rules:
- TEMPORAL EVOLUTION: if the incoming memory reflects a DIFFERENT point in
  time, an updated fact, or a changed state (an opinion, event, or condition
  that evolved), choose "add", NOT "update". Old memories stay useful; a user
  may later refer to a former job, a previous city, or an earlier preference.
- If you choose "update", target_ids MUST come from the listed existing
  memory ids. Never invent or alter an id.
- target_ids must be empty for "add" and "noop".
- Never choose "update" for an existing memory that is not listed.
""".strip()


REWRITE_SYSTEM = """You are an "AlphaAvatar Memory Rewriter".

Your only job is to merge complementary information from an incoming memory
into existing memories. You are NOT deciding whether to create or delete
anything.

Rules:
- Return one object for EACH existing memory you are given, in the SAME order.
- Each rewritten memory must remain self-contained and understandable alone.
- Preserve information already present. Add what the incoming memory
  contributes. Do not drop facts.
- Do not merge in anything that belongs to a different point in time.
- Return only the fields: id, summary, keywords, facts.
""".strip()


JUDGE_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", JUDGE_SYSTEM),
        ("human", "{payload}\n\nOutput only `JudgeVerdicts`."),
    ]
)

REWRITE_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", REWRITE_SYSTEM),
        ("human", "{payload}\n\nOutput only `RewrittenMemories`."),
    ]
)
