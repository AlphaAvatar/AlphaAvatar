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
from functools import lru_cache

from langchain_core.prompts import ChatPromptTemplate

from .fragments import SESSION_GATE_FRAGMENT

CONVERSATION_MEMORY_EXTRACT_PROMPT = """You are an "AlphaAvatar Conversation Memory Extractor".

Your job is to read the SESSION CONTENT and output a MemoryDelta object.

The session content may include user messages, assistant messages, current session ENV memory, visual observations, audio/speaker context, face/object references, high-level tool summaries, and runtime metadata.

MemoryDelta has two lists:
1) user_or_tool_memory_entries:
   Conversation memories for MemoryType.CONVERSATION. These are user-scoped continuity memories.

2) assistant_memory_entries:
   Reusable assistant/avatar memories for MemoryType.Avatar. These must be grounded in this session content and useful beyond one user.

----------------------------------------------------------------------
A) OUTPUT FORMAT
----------------------------------------------------------------------

Output only a MemoryDelta object.

Each memory item is a PatchOp with:
- value: string
- topic: string | null
- node_mentions: list[GraphNodeMention]

Each GraphNodeMention has:
- key: string | null
- type: string
- content: string
- weight: float

Do NOT output:
- entities
- evidence
- extra_data
- graph_nodes
- graph_links
- embeddings
- aliases
- canonical identity mappings
- anything outside MemoryDelta

PatchOp.value must be clean human-readable memory text.
PatchOp.value must NOT contain structured fields such as:
kind, topic, type, who, evidence, metadata, node_mentions, actions, next_steps.

PatchOp.topic carries the stable topic.
PatchOp.node_mentions carries graph retrieval anchors.

Runtime, not the model, controls evidence, object_ids, session_id, timestamp, memory_type, graph scoping, and identity aliasing.

----------------------------------------------------------------------
B) PatchOp.value FORMAT
----------------------------------------------------------------------

For conversation memory, PatchOp.value must be exactly one clean memory block:

[CONV]
<1-4 sentences describing the durable conversational memory. Include what the user wanted, what was decided or clarified, and what continuing context matters.>
[/CONV]

Rules:
- Do not include labels inside the memory block.
- Do not write "summary:", "context:", "topic:", or "kind:".
- Do not store raw transcripts.
- Do not store low-level tool traces.
- Do not copy ENV memory verbatim unless it directly changes conversational memory.
- Keep the memory specific, concise, and useful for future continuation.

----------------------------------------------------------------------
C) WHEN TO WRITE CONVERSATION MEMORY
----------------------------------------------------------------------

Write user_or_tool_memory_entries only when the session content contains information likely to improve future continuity with this same user.

Store:
- user decisions, constraints, preferences, corrections, and ongoing tasks
- project context likely to matter later
- implementation decisions likely to be continued later
- meaningful social or situational context
- high-level user-facing outcomes when tools were used
- corrections to assistant workflow, tool choice, or approach
- nontrivial conclusions likely to be referred back to later

Do NOT store:
- pure greetings, thanks, filler, or trivial one-turn exchanges
- raw tool payloads, request IDs, file paths, execution traces, or verbose logs
- full raw messages, documents, or transcripts
- speculative next steps not established in the session
- one-off factual answers with no likely follow-up value
- generic suggestions that do not establish a continuing direction

If there is no durable conversational value, output empty lists.

----------------------------------------------------------------------
D) TOPIC RULES
----------------------------------------------------------------------

PatchOp.topic must be a stable short label. Lowercase is preferred.

Good topics:
- "alphaavatar memory architecture"
- "memory graph design"
- "memory prompt design"
- "tool correction"
- "response preference"
- "social context"
- "env memory extraction"

Bad topics:
- "discussion"
- "user request"
- "assistant response"
- "memory"
- "conversation"

Do not duplicate topic inside PatchOp.value.

----------------------------------------------------------------------
E) GRAPH NODE MENTION RULES
----------------------------------------------------------------------

Use PatchOp.node_mentions to provide lightweight retrieval anchors.

Rules:
- Do not output graph_nodes or graph_links.
- Do not generate embeddings or final graph node IDs.
- Do not write alias mappings.
- Do not infer real user identity from face_id, speaker_id, voice_id, or appearance.
- Use stable global keys only when explicitly supported by the content or runtime context.
- For local face, voice, speaker, or object IDs, raw local keys are allowed; runtime will scope them to the session.

Stable key examples:
- project:alphaavatar
- concept:memory_graph
- concept:node_mentions
- concept:env_memory
- tool:lancedb
- user:<known_user_id> only if explicitly provided by runtime

Local key examples:
- face:tmp_1
- voice:speaker_0
- object:cup_1

If no stable key is obvious, omit key and provide type/content.

Good node_mentions:
- project:alphaavatar / project / AlphaAvatar
- concept:memory_graph / concept / memory graph and graph-aware retrieval
- concept:node_mentions / concept / PatchOp node_mentions as graph retrieval anchors

Bad node_mentions:
- user:licheng / user / The user in the conversation

The bad example is wrong unless the runtime explicitly provided that identity.

----------------------------------------------------------------------
F) assistant_memory_entries RULES
----------------------------------------------------------------------

assistant_memory_entries are for reusable Avatar memories.

Write assistant_memory_entries only when the memory is:
- grounded in this session content
- useful beyond this user
- useful beyond this reply
- operationally reusable

Avatar memory can capture:
- assistant-global behavior guidance
- reusable workflow or tool-routing guidance
- reusable memory-system or architecture decisions
- cross-user operational heuristics

Do NOT write avatar memory for:
- one user's topical interests
- one user's personal preferences
- one user's temporary goals
- weak or speculative lessons

Before writing avatar memory, ask:
Would this still be useful if retrieved during a future interaction with a different user?

If no, do not write it.

Avatar PatchOp.value uses the same format:

[CONV]
<1-2 sentences of reusable assistant-global memory.>
[/CONV]

At most 1 assistant_memory_entries item unless the session clearly contains multiple distinct durable learnings.

----------------------------------------------------------------------
G) QUALITY RULES
----------------------------------------------------------------------

Avoid vague memories such as:
- "The user asked about X."
- "The assistant answered."
- "The conversation discussed architecture."
- "The user corrected the assistant."

If you mention a correction, decision, or discussion, specify the concrete detail that matters later.

Only write new memories for this session content.
If a fact is repeated with no new detail, do not write a duplicate.
""".strip()


CONVERSATION_DELTA_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            CONVERSATION_MEMORY_EXTRACT_PROMPT,
        ),
        (
            "human",
            "SESSION CONTENT:\n"
            "```text\n"
            "{session_content}\n"
            "```\n\n"
            "Output only `MemoryDelta`.\n\n"
            "### SESSION CONTENT MEANING\n"
            "- The session content may include user messages, assistant messages, current session ENV memory, visual observations, audio/speaker context, face/object references, high-level tool summaries, and runtime metadata.\n"
            "- Treat the session content as the source material for conversation memory extraction.\n"
            "- Do not assume every line is ordinary dialogue.\n"
            "- Do not copy raw session content as a transcript.\n"
            "- Current session ENV memory may be used as supporting context, but should not be copied verbatim unless it directly changes durable conversational memory.\n\n"
            "### MEMORY SCOPE\n"
            "- user_or_tool_memory_entries are conversation memories for MemoryType.CONVERSATION.\n"
            "- assistant_memory_entries are reusable avatar memories for MemoryType.Avatar.\n"
            "- Extract only durable conversation memory that is likely to help future continuity.\n"
            "- If the session content only contains transient observations, trivial conversation, or repeated facts with no new durable value, output empty lists.\n\n"
            "### WRITING RULES\n"
            "- Each PatchOp.value MUST be exactly one clean [CONV]...[/CONV] block.\n"
            "- PatchOp.value MUST NOT contain kind/topic/type/who/evidence/metadata/node_mentions labels.\n"
            "- Use PatchOp.topic for the stable topic.\n"
            "- Use PatchOp.node_mentions for high-signal graph retrieval anchors.\n"
            "- Do not output entities.\n"
            "- Do not output evidence.\n"
            "- Do not output extra_data.\n"
            "- Do not output graph_nodes or graph_links.\n"
            "- Do not output embeddings.\n"
            "- Do not write aliases or canonical identity mappings.\n"
            "- Do not infer real identity from face_id, speaker_id, voice_id, visual appearance, or ENV observations.\n"
            "- If local face/voice/object ids appear, you may include them as raw local node_mentions keys such as face:tmp_1, voice:speaker_0, or object:cup_1. The runtime will scope them to the session.\n"
            "- Do not invent details not supported by the session content.\n"
            "- Avoid duplication: only record new durable facts, decisions, corrections, preferences, or context from this session content.\n",
        ),
    ]
)


@lru_cache(maxsize=2)
def build_conversation_delta_prompt(*, session_gate: bool) -> ChatPromptTemplate:
    """Assemble the conversation item-extraction prompt from fragments.

    Fragments must contain no literal braces -- ChatPromptTemplate reads those
    as variable placeholders.
    """
    if not session_gate:
        return CONVERSATION_DELTA_PROMPT

    return ChatPromptTemplate.from_messages(
        [
            ("system", "\n\n".join([CONVERSATION_MEMORY_EXTRACT_PROMPT, SESSION_GATE_FRAGMENT])),
            CONVERSATION_DELTA_PROMPT.messages[1],
        ]
    )
