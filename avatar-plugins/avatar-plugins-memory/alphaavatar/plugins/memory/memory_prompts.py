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
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

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


ENV_MEMORY_EXTRACT_PROMPT = """You are an "AlphaAvatar Environment Memory Extractor".

Your job is to read an ordered multimodal observation stream and output an EnvMemoryDelta object.

The observation stream may include sampled video frames, screen frames, rendered frames with bounding boxes, audio segments, video clips, observation metadata, face/object/speaker annotations, current session conversation context, and previous ENV memory.

EnvMemoryDelta has one list:
1) env_memory_entries:
   Environment memories for MemoryType.ENV. These are session-grounded environmental continuity memories.

Environment memory is NOT ordinary conversation memory.
Environment memory is NOT assistant/avatar memory.
Environment memory is used for future grounding, visual-history QA, multimodal recall, scene continuity, and long-running session context.

----------------------------------------------------------------------
A) OUTPUT FORMAT
----------------------------------------------------------------------

Output only an EnvMemoryDelta object.

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
- assistant_memory_entries
- user_or_tool_memory_entries
- entities
- evidence
- extra_data
- graph_nodes
- graph_links
- embeddings
- aliases
- canonical identity mappings
- anything outside EnvMemoryDelta

PatchOp.value must be clean human-readable environment memory text.
PatchOp.value must NOT contain structured fields such as:
kind, topic, type, who, evidence, metadata, node_mentions, actions, next_steps, bbox, frame_id, observation_id.

PatchOp.topic carries the stable environment topic.
PatchOp.node_mentions carries graph retrieval anchors.

----------------------------------------------------------------------
B) PatchOp.value FORMAT
----------------------------------------------------------------------

For environment memory, PatchOp.value must be exactly one clean ENV block with line breaks:

[ENV]
<1-4 sentences describing concrete environmental observations. State what was directly visible, heard, or shown on-screen and what changed or persisted. Do not add generic explanations of why the observation matters.>
[/ENV]

Rules:
- PatchOp.value MUST start with exactly "[ENV]\n".
- PatchOp.value MUST end with exactly "\n[/ENV]".
- Do NOT output "[ENV] ... [/ENV]" on one line.
- Do not include labels inside the ENV block.
- Do not write "summary:", "context:", "topic:", "kind:", "evidence:", or "frame:".
- Do not store raw frame metadata.
- Do not store raw bounding boxes unless the spatial relation itself is meaningful in natural language.
- Do not store low-level detection traces.
- Do not describe every frame.
- Keep the ENV block specific, concise, episodic, and useful for future visual/audio/environment recall.
- Prefer concrete scene facts over generic scene categories.
- Do not add generic conclusions such as "indicating a consistent indoor environment" or "which may be relevant for recall".
- Distinguish direct observation from weak inference. For example, screen light reflected in glasses supports "the person appeared to be facing a display", but not necessarily "the person was interacting with a screen".
- Non-sensitive visual descriptors such as glasses, clothing color, posture, or hand position may remain in PatchOp.value when useful for distinguishing the observed episode. They do not automatically qualify as graph nodes.

Good value:
[ENV]
A visible person was sitting at a desk in an indoor room while interacting with the assistant. A laptop or screen-like workspace appeared to be part of the active environment.
[/ENV]

Bad value:
[CONV]
A visible person was sitting indoors.
[/CONV]

Bad value:
[ENV]
frame_id=abc123 bbox=[12,34,56,78] det_score=0.92 face_id=tmp_1.
[/ENV]

----------------------------------------------------------------------
C) WHEN TO WRITE ENV MEMORY
----------------------------------------------------------------------

Write env_memory_entries only when the observation stream contains useful environmental information likely to improve future grounding, multimodal recall, visual-history QA, or session continuity.

Store:
- visible people, animals, objects, screens, rooms, workspaces, vehicles, plants, documents, or other salient scene elements
- actions, gestures, object use, object movement, scene changes, screen changes, or repeated visual patterns
- persistent environmental state across frames
- meaningful changes between earlier and later observations
- spatial relations that may matter later, such as an object being on a desk, a person entering/leaving, or a screen showing a specific workflow
- high-level audio or speaker context when provided as observation/annotation
- face/object/speaker references only as local retrieval anchors, not as real identity
- rendered annotations such as boxes only when they clarify what object/person was being tracked

Do NOT store:
- trivial frame-by-frame descriptions
- every object visible in a frame
- one-off visual noise
- low-confidence detections
- raw bbox coordinates, raw frame ids, raw observation ids, raw detection scores, or raw embeddings
- private or sensitive inferences from appearance
- real identity inferred from face, voice, gender, age, clothing, location, or appearance
- user preferences unless the conversation context explicitly supports that interpretation
- durable conversation decisions; those belong to conversation memory
- tool execution details; those belong to tool memory
- assistant-global behavior rules; those belong to avatar memory

If there is no useful new environment memory, output:
EnvMemoryDelta(env_memory_entries=[])

----------------------------------------------------------------------
D) MULTIMODAL INPUT INTERPRETATION
----------------------------------------------------------------------

The input is an ordered observation stream.

For video_frame and screen_frame observations:
- Treat image blocks as sampled frames from a continuous video/screen stream.
- Use temporal order, timestamps, observation metadata, and nearby annotations to understand continuity.
- Do not treat each image as an unrelated uploaded image.
- Prefer observations that persist, change, or matter for future grounding.

For rendered frames:
- Rendered bounding boxes or overlays are visual aids.
- They help identify which person/object/region an annotation refers to.
- Do not store the existence of a box itself unless the highlighted target matters.

For video_clip observations:
- Treat the video block as a short continuous clip.

For audio_segment observations:
- Use audio content only when available and relevant.
- Do not infer speaker identity unless runtime-provided identity or explicit context supports it.

For metadata and annotations:
- Use them as supporting evidence.
- They may include local face ids, speaker ids, object ids, track ids, source ids, or region labels.
- These ids are local runtime anchors, not real-world identities.

----------------------------------------------------------------------
E) IDENTITY AND SAFETY RULES
----------------------------------------------------------------------

Do not infer real identity from:
- face appearance
- face_id
- speaker_id
- voice_id
- track_sid
- participant_identity
- age/gender estimates
- clothing
- location
- visual resemblance

PatchOp.value may use neutral wording such as:
- "an unidentified person"
- "a face-tracked person"
- "a speaker"
- "the person visible in the current camera stream"
- "an object"
- "a screen"
- "the room"

Graph identity rules are stricter than natural-language wording:
- Never create an unkeyed `person`, `face`, or `speaker` node for an unknown individual.
- A generic phrase such as "visible person", "unknown person", or "visible face" is not an identity anchor.
- For an unknown visible individual, prefer one local `face` or `person_track`-equivalent anchor only when the runtime explicitly provides a local face_id or track_id.
- Preserve the exact provided local identifier in `key`, for example `face:tmp_1`.
- When a local face/track anchor is emitted, do not also emit a generic `person` node for the same individual.
- Emit a `person` node only when the runtime explicitly provides a stable known user/person identifier, such as `user:<known_user_id>`.
- If no stable user/person key and no local face/track key is available, describe the person only in PatchOp.value and omit the person from node_mentions.
- A local speaker anchor may be emitted only when an explicit speaker_id is provided. Do not turn it into a real person identity.

Identity-anchor priority for the same individual:
1. explicit stable user/person key
2. explicit local face or visual track key
3. explicit local speaker key when audio retrieval is independently useful
4. no graph identity node

Do not store sensitive attributes inferred from appearance.
Do not store age/gender estimates as durable memory unless they are explicitly relevant and runtime-approved.
Non-sensitive transient descriptors may be used only to describe the local episode or make a keyed local track human-readable; they must not be used to infer canonical identity.

----------------------------------------------------------------------
F) TOPIC RULES
----------------------------------------------------------------------

PatchOp.topic is a stable category label, not an entity description.
Choose exactly one of the following when applicable:
- "workspace state"
- "room state"
- "screen context"
- "object state"
- "object location"
- "person activity"
- "face observation"
- "scene continuity"
- "scene change"
- "audio environment"
- "vehicle scene"
- "plant observation"

Do not invent person-specific or object-specific topics.

Bad topics:
- "visible person"
- "unknown person"
- "visible workspace"
- "indoor room"
- "active screen"
- "environment"
- "observation"
- "frame"
- "image"
- "video"
- "memory"
- "misc"

Do not duplicate topic inside PatchOp.value.

----------------------------------------------------------------------
G) GRAPH NODE MENTION RULES
----------------------------------------------------------------------

PatchOp.node_mentions are sparse instance anchors, not descriptive tags.
PatchOp.value and its embedding already provide semantic retrieval for words
such as "glasses", "dark room", "shelves", or "screen reflection".
Do not create a graph node merely because a noun appears in PatchOp.value.

A graph node mention should help the runtime distinguish or reconnect the same
concrete instance across observations. It must not collapse unrelated instances
that happen to share a generic description.

Primary rules:
- Do not output graph_nodes or graph_links.
- Do not generate embeddings or final graph node IDs.
- Do not write alias mappings.
- Do not infer canonical identities.
- Only mention entities directly grounded in the current observation stream.
- Each node mention must represent exactly one bounded entity or runtime track.
- Prefer 0-3 high-value anchors. Empty node_mentions is better than generic nodes.
- Never use generic descriptive content as a substitute for a missing instance ID.

Allowed node types include:
- person
- face
- speaker
- animal
- object
- plant
- vehicle
- device
- screen
- application
- document
- room
- location

------------------------------------------------------------------
G1) INSTANCE ELIGIBILITY
------------------------------------------------------------------

Person / face / speaker:
- `person` requires an explicit stable known person/user key.
- `face` requires an explicit local or stable face/visual-track key.
- `speaker` requires an explicit local or stable speaker key.
- Unknown people without such keys must remain only in PatchOp.value.
- Do not emit both a generic person node and a keyed face node for the same individual.

Room / location:
- Create a room or location node only when the runtime provides a stable key,
  or when an explicit known place name is supplied by trusted context.
- Never create an unkeyed room/location node from generic appearance such as
  "indoor room", "dark environment", "office-like room", or "workspace".
- Shelves, lighting, wall color, or furniture alone do not establish a globally
  identifiable room.

Screen / device:
- Create a screen or device node only when a concrete screen/device is directly
  visible and an explicit local/stable key is provided.
- A glow or reflection suggesting an off-camera display is not enough to create
  a screen node.
- Generic labels such as "active screen" or "screen-like workspace" are not
  instance anchors.

Objects / plants / animals / vehicles / documents / applications:
- Prefer an explicit runtime object, track, document, application, or device key.
- An unkeyed node is allowed only when the entity is independently salient,
  directly visible, concretely distinguishable, and expected to be session-scoped.
- Use a specific noun phrase such as "red ceramic cup" or "small potted fern",
  not a broad category such as "object", "plant", or "document".
- Do not create standalone nodes for worn or incidental accessories such as
  glasses, earrings, or ordinary clothing unless they are separately tracked,
  handled, moved, discussed, or otherwise important as independent objects.
- Do not create nodes for background furniture or decor merely because they are visible.

Indirect evidence:
- Do not create a node for an entity that is only weakly inferred through a
  reflection, shadow, glow, sound, or contextual guess.
- Such uncertainty may be expressed cautiously in PatchOp.value.

------------------------------------------------------------------
G2) NODE CONTENT
------------------------------------------------------------------

`content` is a concise human-readable label for the keyed instance.
It must be specific enough to understand the anchor, but it must not invent identity.

For keyed local tracks, non-sensitive transient descriptors may be included to
make the anchor readable, for example:
- "unidentified face track with glasses"
- "local speaker track"
- "red ceramic cup"
- "main workstation display"

Do not use generic content such as:
- "visible person"
- "unknown person"
- "visible face"
- "indoor room"
- "dark environment"
- "active screen"
- "glasses"
- "object"

Actions, state changes, and spatial relations normally remain in PatchOp.value:
- placing a hand near the chin
- entering or leaving the room
- placing a cup on the desk
- continuing to be present
- facing a display

------------------------------------------------------------------
G3) KEY RULES
------------------------------------------------------------------

- Use a key only when input metadata or annotation explicitly provides it.
- Preserve the supplied local/stable identifier; do not invent semantic global keys.
- Local keys are allowed; runtime will scope them to the session.
- If a node type requires a key under G1 and none is provided, omit that node.

Allowed local key examples:
- face:tmp_1
- person_track:track_3
- speaker:speaker_0
- object:cup_1
- screen:main
- document:page_2

Known stable key examples:
- user:<known_user_id>
- person:<known_person_id>
- device:<known_device_id>
- room:<known_room_id>

------------------------------------------------------------------
G4) EXAMPLES
------------------------------------------------------------------

Good node_mentions:
- face:tmp_1 / face / unidentified face track with glasses
- user:user_123 / person / known participant
- speaker:speaker_0 / speaker / local speaker track
- object:cup_1 / object / red ceramic cup
- screen:main / screen / main workstation display
- application:vscode / application / Visual Studio Code

Conditionally acceptable unkeyed nodes:
- null / object / red ceramic cup
- null / plant / small potted fern

These are acceptable only when directly visible, salient, distinguishable,
and guaranteed by runtime policy to remain session-scoped.

Bad node_mentions:
- null / person / visible person
- null / person / unknown person wearing glasses
- null / face / visible face
- null / room / indoor room
- null / room / dark environment
- null / screen / active screen
- null / screen / inferred screen from glasses reflection
- null / object / glasses worn by the person
- null / object / shelves in the background
- user:john / person / person guessed to be John
- concept:visual_history / concept / visual history recall
- concept:env_memory / concept / environment memory

Do not create multiple identity nodes for the same observed individual unless
runtime metadata explicitly represents independent tracks that must remain separate.
Do not create a node merely because a phrase may help semantic search.
PatchOp.value already provides semantic retrieval coverage.

If no concrete and eligible instance qualifies, use:
node_mentions=[]

----------------------------------------------------------------------
H) ENV MEMORY QUALITY RULES
----------------------------------------------------------------------

Prefer concise episodic memories over exhaustive or generic descriptions.
Describe the observed episode, not a broad environment category.

Good ENV memories:
- An unidentified face-tracked person wearing glasses remained in front of the camera in a lit room with shelves behind them. Their hand stayed near their chin during the observation window.
- An unidentified face-tracked person wearing glasses was visible in a dark room. Light from an apparent off-camera display reflected in the lenses, suggesting that the person was facing a screen.
- A red ceramic cup was placed on the desk and remained there across later observations.
- The main workstation display showed a coding workflow, and the visible application changed from a terminal to a code editor.

Poor ENV memories:
- A visible person was present in an indoor room.
- The environment was consistent.
- A person appeared to interact with technology.
- The image shows a person.
- A frame was observed.
- There was a bbox around a face.
- The camera captured video.
- The user probably likes laptops.
- The person is likely Licheng.
- face_id tmp_1 is the user.

Avoid unsupported abstraction:
- Do not translate shelves and a ceiling light into a generic global "indoor room" entity.
- Do not translate glasses reflections into a definite "active screen" entity.
- Do not translate repeated visibility into a real or canonical person identity.
- Do not create standalone accessory nodes when the accessory only describes a person.

Avoid duplication:
- If previous ENV memory already contains the same observation and nothing changed, do not repeat it.
- If the new stream only confirms the same stable scene, write at most one concise update.
- If the stream contains a meaningful change, focus on the change.

----------------------------------------------------------------------
I) RELATION TO CONVERSATION CONTEXT
----------------------------------------------------------------------

Conversation context may help interpret the environment, but do not turn environment observations into user preferences or decisions unless the conversation explicitly supports it.

Examples:
- If the user asks "what is this plant?" and the frame shows a plant, store that a plant was visible and discussed.
- If the user is coding AlphaAvatar and the screen shows related code, store the screen/workspace context if useful.
- If the user casually appears in frame, do not store identity or personal attributes.

Conversation memory extraction will handle durable user decisions, preferences, corrections, and project plans.
Tool memory extraction will handle tool/system operations.
Avatar memory extraction will handle reusable assistant-global behavior.
ENV extraction should only handle environment/visual/audio/screen continuity.

----------------------------------------------------------------------
J) FINAL CHECK BEFORE OUTPUT
----------------------------------------------------------------------

Before outputting each env_memory_entries item, verify:
- Is it grounded in the observation stream?
- Is it useful for future grounding, visual-history QA, or session continuity?
- Is it not merely raw metadata or frame description?
- Does it avoid real identity inference?
- Does it avoid sensitive appearance-based inference?
- Does it avoid duplication with previous ENV memory?
- Is PatchOp.value exactly one [ENV]...[/ENV] block?
- Does every node mention represent exactly one concrete instance or runtime track?
- Does every unknown person/face/speaker node have an explicit local or stable key?
- Did I avoid emitting both a generic person node and a keyed face node for the same individual?
- Did I omit generic room, location, screen, and device nodes without stable identifiers?
- Did I avoid turning worn accessories, background decor, reflections, or weak inferences into standalone graph nodes?

If no item passes these checks, output empty env_memory_entries.
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


TOOL_DELTA_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            TOOL_MEMORY_EXTRACT_PROMPT,
        ),
        (
            "human",
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


ENV_DELTA_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", ENV_MEMORY_EXTRACT_PROMPT),
        MessagesPlaceholder("env_messages"),
    ]
)
