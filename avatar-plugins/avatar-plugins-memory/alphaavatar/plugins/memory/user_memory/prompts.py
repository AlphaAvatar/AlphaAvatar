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

_RETENTION_RULES = """
Preserve these when the session contains them:

- the purpose behind what the user is doing
- the current blocker
- approaches the user tried and rejected, and why
- the user's feedback about the assistant's behaviour
""".strip()


_CONSOLIDATION_SYSTEM = f"""
You consolidate durable AlphaAvatar memories.

Atomic memories are immutable source records. Consolidated memories combine
related source memories into a coherent current representation.

For every incoming atomic memory:

- assign it to an existing consolidated memory when it belongs to the same
  event, project, preference, state, or ongoing thread;
- use "new:1", "new:2", ... when it belongs to a new subject;
- do not group unrelated memories merely because they came from one session.

When new information conflicts with an existing consolidated memory, use the
session content to determine whether it is:

- a correction,
- a change over time,
- an addition,
- or an unresolved disagreement.

Do not infer a correction from difference alone.

The resulting consolidated memory must be understandable later without the
original transcript and must not invent unsupported information.

{_RETENTION_RULES}
""".strip()


_CONSOLIDATION_HUMAN = """
SESSION CONTENT:
```text
{session_content}
```

INCOMING ATOMIC MEMORIES:
```text
{incoming}
```

EXISTING CONSOLIDATED MEMORIES:
```text
{candidates}
```

Output only ConsolidationPlan.

Every incoming memory id must appear exactly once as source_memory_id.
Each assignment must provide target_memory_id and a short reason.
Every target id must appear in memories with a non-empty value.
""".strip()


CONSOLIDATION_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", _CONSOLIDATION_SYSTEM),
        ("human", _CONSOLIDATION_HUMAN),
    ]
)


_SESSION_SUMMARY_SYSTEM = f"""
Create one consolidated memory from the current session.

Atomic memories are already stored independently. The consolidated memory
should preserve useful context that atomic extraction may omit rather than
merely repeating each atomic statement.

Write natural prose that remains understandable later without the transcript.
Do not invent unsupported information.

{_RETENTION_RULES}

Use target memory id "new:1" and assign every incoming memory to it.
""".strip()


SESSION_SUMMARY_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", _SESSION_SUMMARY_SYSTEM),
        (
            "human",
            """
            SESSION CONTENT:
            ```text
            {session_content}
            ```

            INCOMING ATOMIC MEMORIES:
            ```text
            {incoming}
            ```

            Output only ConsolidationPlan.
            """.strip(),
        ),
    ]
)


def render_incoming(items) -> str:
    return "\n".join(f"- id={item.memory_id}: {item.render_line()}" for item in items)


def render_candidates(memories) -> str:
    if not memories:
        return "(none)"

    return "\n".join(
        (
            f"- id={memory.memory_id} "
            f"(sources={len(memory.source_memory_ids)}, "
            f"revision={memory.revision}): "
            f"{memory.render_line()}"
        )
        for memory in memories
    )
