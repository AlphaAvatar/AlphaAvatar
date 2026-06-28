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
from langchain_core.prompts import ChatPromptTemplate

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

[MEMORY]
<1-4 sentences describing the durable conversational memory. Include what the user wanted, what was decided or clarified, and what continuing context matters.>
[/MEMORY]

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

[MEMORY]
<1-2 sentences of reusable assistant-global memory.>
[/MEMORY]

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


TOOL_MEMORY_EXTRACT_PROMPT = """You are an "AlphaAvatar Tool Memory Extractor".

Your job is to read the SESSION CONTENT and output a MemoryDelta object.

The session content may include user messages, assistant messages, function calls, function call outputs, tool payloads, tool results, file operations, search results, retrieval outputs, indexing events, artifact generation events, graph/VDB operations, system errors, retries, fallbacks, and metadata.

MemoryDelta has two lists:
1) user_or_tool_memory_entries:
   Tool memories for MemoryType.TOOLS. These describe assistant↔tool interactions and system operations.

2) assistant_memory_entries:
   Reusable assistant/avatar memories for MemoryType.Avatar. These must be grounded in concrete tool/system events and useful beyond one user.

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

PatchOp.value must be clean human-readable tool memory content.
PatchOp.value must NOT contain structured fields such as:
type, who, topic, component, inputs, outcome, evidence, error, actions, metadata, node_mentions.

PatchOp.topic carries the stable topic.
PatchOp.node_mentions carries graph retrieval anchors.

Runtime, not the model, controls evidence, object_ids, session_id, timestamp, memory_type, graph scoping, and identity aliasing.

----------------------------------------------------------------------
B) TOOL EVENT GATE
----------------------------------------------------------------------

Before writing any memory, decide whether the session content contains an explicit tool/system operation.

Valid tool/system events include:
- FunctionCall, FunctionCallOutput, tool_calls, function_call, ToolMessage
- explicit tool output
- file read/write/save/index/delete/generation
- search, retrieval, indexing, download, scrape
- VDB/database operation
- graph/index/storage operation
- explicit tool error, timeout, retry, fallback, or config update
- artifact generation or export

These are NOT tool events by themselves:
- normal ChatMessage
- normal assistant reply
- normal user message
- ImageContent or VideoFrame
- visual input or sampled frames
- audio transcript text
- ENV memory
- multimodal understanding without explicit tool/system operation
- latency metrics unless they show an explicit incident

Do not infer an internal tool/component from multimodal understanding.
Do not invent components such as visual_analysis_module, vision_tool, image_analyzer, env_memory_tool, or multimodal_module unless explicitly present.

If there is no explicit tool/system event, output MemoryDelta with both lists empty.

----------------------------------------------------------------------
C) PatchOp.value FORMAT
----------------------------------------------------------------------

For tool memory, PatchOp.value must be exactly one clean event block:

[EVENT]
<2-5 sentences describing the concrete tool episode. Include the component or tool name if known, the operation performed, the outcome, and useful sanitized operational detail.>
[/EVENT]

Rules:
- Do not include labels inside the event block.
- Do not write "type:", "who:", "topic:", "component:", "inputs:", "outcome:", "evidence:", "error:", or "actions:".
- Do not store raw payloads.
- Do not store full tool outputs unless short and essential.
- Prefer one memory item per tool episode, not one item per individual call.

----------------------------------------------------------------------
D) WHEN TO WRITE TOOL MEMORY
----------------------------------------------------------------------

Write user_or_tool_memory_entries when any of these happens:
1) A real tool was called.
2) A file was read, written, saved, indexed, deleted, or generated.
3) A search, retrieval, indexing, download, scrape, or database operation happened.
4) A VDB, RAG, graph, memory, or storage operation happened.
5) A tool/system failure, retry, fallback, timeout, or config change occurred.
6) The assistant switched tool/workflow path after a correction.
7) A generated artifact was created, modified, saved, or exported.
8) A tool execution result changes what should be remembered for future operations.

Do not write tool memory for ordinary conversation without explicit tool/system operation.
Do not store ENV observations as tool memory merely because they appear in session content.

----------------------------------------------------------------------
E) TOOL EPISODE AGGREGATION
----------------------------------------------------------------------

Prefer one memory item per tool episode.

A tool episode is a group of consecutive tool/system operations sharing:
- the same component/tool
- the same immediate goal
- the same operational phase

Merge repeated calls when they are part of one broader activity:
- multiple web searches for one information need
- repeated retrieval attempts for the same goal
- multiple file reads used to inspect one module
- multiple VDB operations for one save/search path
- multiple graph JSONL operations for one graph update

Create separate memory items only when there is a meaningful boundary:
- different tool/component
- different goal
- change of phase such as search -> read -> save -> index
- failure, retry, fallback, or config change
- user correction that changes the tool path
- artifact generation separate from retrieval

----------------------------------------------------------------------
F) TOPIC RULES
----------------------------------------------------------------------

PatchOp.topic must be a stable short label. Lowercase is preferred.

Good topics:
- "web search"
- "file inspection"
- "memory graph indexing"
- "lancedb memory save"
- "graph alias storage"
- "rag indexing failure"
- "artifact generation"
- "tool path correction"
- "vdb retrieval"
- "config update"

Bad topics:
- "tool"
- "operation"
- "task"
- "success"
- "assistant action"

Do not duplicate topic inside PatchOp.value.

----------------------------------------------------------------------
G) GRAPH NODE MENTION RULES
----------------------------------------------------------------------

Use PatchOp.node_mentions to provide lightweight retrieval anchors.

Rules:
- Do not output graph_nodes or graph_links.
- Do not generate embeddings or final graph node IDs.
- Do not write alias mappings.
- Do not infer real identity from face_id, speaker_id, voice_id, or visual appearance.
- For tools, modules, operations, errors, artifacts, and concepts, prefer stable keys when obvious.
- For local face, voice, speaker, or object IDs, raw local keys are allowed; runtime will scope them to the session.

Stable key examples:
- tool:lancedb
- tool:qdrant
- tool:web_run
- tool:file_search
- tool:raganythingtool
- project:alphaavatar
- concept:memory_graph
- concept:vdb_save
- concept:graph_alias
- concept:http_502
- artifact:memory_prompts_py
- user:<known_user_id> only if explicitly provided by runtime

Local key examples:
- face:tmp_1
- voice:speaker_0
- object:cup_1

If no stable key is obvious, omit key and provide type/content.

----------------------------------------------------------------------
H) assistant_memory_entries RULES
----------------------------------------------------------------------

assistant_memory_entries are for reusable Avatar memories grounded in tool/system events.

Write assistant memory only when it is:
- grounded in a concrete tool/system event from this session
- useful beyond this user
- useful beyond this reply
- operationally reusable

Use assistant_memory_entries for:
- reusable tool-routing rules
- reusable fallback or retry policy
- reusable storage/indexing rules
- reusable artifact generation guidance
- reusable conversation/tool memory separation rules
- corrected workflow guidance when the correction generalizes

Do NOT write assistant memory for:
- a mere fact that a tool was run
- one user's temporary task
- generic "more debugging may be needed"
- generic "assistant used search"
- weak or speculative lessons

Avatar PatchOp.value uses the same clean event format:

[EVENT]
<1-3 sentences describing the reusable operational rule grounded in this session.>
[/EVENT]

At most 1 assistant_memory_entries item unless the session clearly contains multiple durable operational learnings.

----------------------------------------------------------------------
I) QUALITY RULES
----------------------------------------------------------------------

Only write new memories for this session content.
If the same event is repeated with no new details, do not add a duplicate.
Aggregate repeated operations into one tool episode unless there is a meaningful boundary.

If a tool helped answer the user:
- tool memory records the operation itself
- conversation memory records user-facing continuity
- do not restate the full conversation summary in tool memory unless needed to explain the tool event
""".strip()


CONVERSATION_DELTA_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            CONVERSATION_MEMORY_EXTRACT_PROMPT,
        ),
        (
            "human",
            "SESSION CONTENT TYPE: {type}\n"
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
            "- Each PatchOp.value MUST be exactly one clean [MEMORY]...[/MEMORY] block.\n"
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


TOOL_DELTA_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            TOOL_MEMORY_EXTRACT_PROMPT,
        ),
        (
            "human",
            "SESSION CONTENT TYPE: {type}\n"
            "SESSION CONTENT:\n"
            "```text\n"
            "{session_content}\n"
            "```\n\n"
            "Output only `MemoryDelta`.\n\n"
            "### SESSION CONTENT MEANING\n"
            "- The session content may include user messages, assistant messages, current session ENV memory, visual observations, audio/speaker context, face/object references, tool calls, tool outputs, high-level tool summaries, file operations, search/retrieval/indexing events, artifact operations, VDB operations, graph storage operations, system errors, retries, fallbacks, and runtime metadata.\n"
            "- Treat the session content as the source material for tool/system memory extraction.\n"
            "- Do not assume every line is a tool event.\n"
            "- Do not convert ordinary conversation, visual observations, ENV memory, or multimodal context into tool memory unless an explicit tool/system operation occurred.\n\n"
            "### TOOL EVENT GATE\n"
            "- Before writing any memory, decide whether the session content contains an explicit tool/system operation.\n"
            "- A valid tool event requires explicit evidence in the session content, such as FunctionCall, FunctionCallOutput, tool_calls, function_call, ToolMessage, tool output, file read/write/save/index/delete/generation, search/retrieval/indexing/download/scrape, VDB/database operation, graph/index/storage operation, explicit tool error, timeout, retry, fallback, config update, or artifact generation.\n"
            "- ChatMessage, normal assistant replies, normal user messages, ImageContent, VideoFrame, visual input, sampled frames, audio/transcript text, ENV memory, and latency metrics are NOT tool events by themselves.\n"
            "- Assistant visual reasoning over attached frames is not artifact_generation and not tool memory.\n"
            "- Runtime metrics such as TTS/STT/LLM latency are not tool memories unless they show an explicit incident, failure, retry, fallback, or config change.\n"
            "- Do not infer an internal tool/component from multimodal understanding.\n"
            "- Do not invent components such as visual_analysis_module, vision_tool, image_analyzer, env_memory_tool, or multimodal_module unless they explicitly appear in the session content.\n"
            "- If there is no explicit tool/system event, output MemoryDelta with both lists empty.\n\n"
            "### MEMORY SCOPE\n"
            "- user_or_tool_memory_entries are tool memories for MemoryType.TOOLS.\n"
            "- assistant_memory_entries are reusable avatar memories for MemoryType.Avatar derived from concrete tool/system events.\n"
            "- ENV memory may be used as surrounding context only when it helps explain an explicit tool/system operation.\n"
            "- Do not store ENV observations as tool memory merely because they appear in the session content.\n\n"
            "### WRITING RULES\n"
            "- Each PatchOp.value MUST be exactly one clean [EVENT]...[/EVENT] block.\n"
            "- PatchOp.value MUST NOT contain type/who/topic/component/inputs/outcome/evidence/error/actions/metadata/node_mentions labels.\n"
            "- Use PatchOp.topic for the stable topic.\n"
            "- Use PatchOp.node_mentions for tool names, modules, operations, error identifiers, artifact types, graph concepts, VDB concepts, and other high-signal retrieval anchors.\n"
            "- Do not output entities.\n"
            "- Do not output evidence.\n"
            "- Do not output extra_data.\n"
            "- Do not output graph_nodes or graph_links.\n"
            "- Do not output embeddings.\n"
            "- Do not write aliases or canonical identity mappings.\n"
            "- Do not infer real identity from face_id, speaker_id, voice_id, visual appearance, or ENV observations.\n"
            "- If local face/voice/object ids appear in an explicit tool/system event, you may include them as raw local node_mentions keys such as face:tmp_1, voice:speaker_0, or object:cup_1. The runtime will scope them to the session.\n"
            "- Include concrete component, operation, outcome, and relevant sanitized details in PatchOp.value when supported by the session content.\n"
            "- Aggregate repeated operations into one tool episode unless there is a meaningful boundary such as a different component, phase, failure, retry, fallback, or correction.\n"
            "- Do not invent details not supported by the session content.\n",
        ),
    ]
)
