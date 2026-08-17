# 📈 **MAIN GOAL**

> **Build a universal multimodal personal assistant** capable of recognizing users through streaming voice, text, image, and video input.

> It should possess **self-memory**, **persona awareness**, **autonomous reflection**, **planning ability**, **iterative self-evolution**, and **real-time interaction feedback**.

> The assistant will **seamlessly integrate** with mainstream external tools and personal workspaces to solve practical problems efficiently.

---

# Table of contents

* [PLAN OVERVIEW](#plan-overview)
* [AlphaAvatar Core](#alphaavatar-core)
* [AlphaAvatar RTC](#alphaavatar-rtc)
* [AlphaAvatar Agent](#alphaavatar-agent)

  * [Core Function](#core-function)
  * [Prompt & Context](#prompt-context)
  * [Runtime](#runtime)
  * [Vision](#vision)
* [AlphaAvatar Plugins](#alphaavatar-plugins)

  * [STATUS](#status)
  * [INTERACTION ROUTER](#interaction-router)
  * [CHARACTER](#character)
  * [MEMORY](#memory)
  * [PERSONA](#persona)
  * [REFLECTION](#reflection)
  * [PLANNING](#planning)
  * [BEHAVIOR](#behavior)
* [Tools Plugins](#tools-plugins)

  * [DeepResearch](#deepresearch)
  * [RAG](#rag)
  * [MCP](#mcp)
* [Channels](#channels)

  * [Web Demo](#web-demo)
  * [WhatsApp](#whatsapp)
* [NEXT STEPS](#next-steps)

---

# 🗓️ PLAN OVERVIEW

| Plugin / System           | Description                                                                                                                           |     Stage     |
| :------------------------ | :------------------------------------------------------------------------------------------------------------------------------------ | :-----------: |
| 🎯 **Interaction Router** | Routes shared realtime input and output processing through VAD, STT, speech synthesis, transcript synchronization, and cancellation, and will gradually take ownership of native turn and response decisions. | ⏳ In Progress |
| 💡 **Reflection**         | Generates metacognitive insights from memory, persona, tool usage, failures, and interaction history.                                 |   🧩 Planned  |
| 📅 **Planning**           | Generates short-term tasks, long-term plans, reminders, and follow-up actions from memory, reflection, and tool results.              |   🧩 Planned  |
| ⚙️ **Behavior**           | Controls response style, workflow selection, tool-use policy, and proactive assistance rules.                                         |   🧩 Planned  |
| 🌍 **World Sandbox**      | Enables AlphaAvatar to interact with external virtual environments, code sandboxes, simulated worlds, or apps.                        |   🧩 Planned  |

---

# AlphaAvatar Core

### ✅ DONE

| Date    | Milestone                              | Notes |
| :------ | :------------------------------------- | :---- |
| 2026-07 | **Environment Observation Model**      | Added transport-agnostic `EnvObservation` and `EnvAnnotation` models for video, audio, screen, event, and future multimodal inputs. |
| 2026-07 | **Multi-representation Media Payload** | Added `MediaPayload`, `PayloadFormat`, `PayloadView`, and AlphaAvatar-owned video-frame representations without RTC-specific types. |
| 2026-07 | **Typed Perception Runtime**           | Added independent video, audio, screen, event, and annotation streams with consumer-specific cursors. |
| 2026-07 | **Shared Timeline and Window Builder** | Added observation–annotation alignment and ordered consumer windows for Persona, Memory, Vision, and future routers. |
| 2026-07 | **Shared Audio and Speech Perception** | Added normalized audio observations and a derived speech stream, allowing Router, transcription, speaker recognition, and future audio processors to consume the same source independently. |
| 2026-08 | **Unified Temporal Runtime** | Added `RuntimeClock`, `RuntimeTime`, `RuntimeTimeRange`, ordered perception events, source-state tracking, immutable perception cutoffs, and shared multimodal temporal alignment. |
| 2026-08 | **Time-based Perception Retention** | Replaced modality-owned fixed stream sizes with configurable retention derived from producer cadence, retention horizon, and safety headroom. |
| 2026-08 | **Typed Perception Contracts v2** | Stream, observation, event, and media-source kinds now use explicit enums and schemas across the perception runtime. |
| 2026-08 | **Transport-independent Output Runtime** | Added AlphaAvatar-owned output streams, output timelines, delivery state, interruption semantics, and playback-aware output tracking. |

### 🧭 TODO

| Priority | Task | Stage |
| :------- | :--- | :---: |
| 🔸 | Add source-aware retention, payload pruning, backpressure, and consumer-lag observability for long-running and multi-source sessions. | ⏳ In Progress |
| 🔹 | Extend temporal alignment to richer multi-source, multi-speaker, annotation-fusion, and long-running event scenarios. | 🧩 Planned |
| 🔹 | Add annotation fusion for face, speaker, object, action, scene, and screen understanding. | 🧩 Planned |
| 🔹 | Add reusable core policies for observation selection, temporal windows, and payload lifecycle management. | 🧩 Planned |

---

# AlphaAvatar RTC

### ✅ DONE

| Date    | Milestone                         | Notes |
| :------ | :-------------------------------- | :---- |
| 2026-07 | **RTC Adapter Boundary**          | RTC-specific media conversion is isolated from `avatar-core`; core observations no longer store LiveKit frame types directly. |
| 2026-07 | **LiveKit Video Input Runtime**   | LiveKit video frames are normalized into AlphaAvatar media payloads and published once into `PerceptionRuntime`. |
| 2026-07 | **Model-bound Frame Conversion**  | Generic AlphaAvatar frames are converted back to LiveKit frames only at the LiveKit model adapter boundary. |
| 2026-07 | **LiveKit Audio Input Runtime**   | LiveKit microphone frames are normalized into AlphaAvatar audio payloads and published once into `PerceptionRuntime.audio`. |

### 🧭 TODO

| Priority | Task | Stage |
| :------- | :--- | :---: |
| 🔸 | Extract reusable RTC interfaces and adapters into a standalone `avatar-rtc` package. | ⏳ In Progress |
| 🔸 | Add unified screen-share, data-channel, and output adapters on top of the RTC abstraction. | ⏳ In Progress |
| 🔹 | Add alternative RTC backends such as native WebRTC, `aiortc`, and custom RTC providers. | 🧩 Planned |
| 🔹 | Add RTC-level reconnect, transport recovery, flow control, and health monitoring. | 🧩 Planned |

---

# AlphaAvatar Agent

## Core Function

### ✅ DONE

| Date    | Task                                                                                                                                                                                            |
| :------ | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2025-10 | Developed a context manager to route real-time updated interaction information to plugin models such as memory and persona.                                                                     |
| 2026-05 | Added mutable user-scoped working directory support through `UserPath`, enabling plugins to follow identity changes dynamically.                                                                |
| 2026-05 | Added temporary-user to real-user identity resolution flow, including deferred temporary directory migration and cleanup at session exit.                                                       |
| 2026-05 | Added runtime-aware session context construction based on room type, session mode, modality availability, user metadata, and time context.                                                      |
| 2026-05 | Added LiveKit room binding support for runtime components that need direct room-level access, such as status sinks and data channel publishers.                                                 |
| 2026-06 | Introduced a unified provider layer for task-based LLM and embedding calls, including structured output, usage normalization, provider tracing, and provider-based Memory / Persona extraction. |
| 2026-06 | Refactored runtime and configuration foundations with `SessionRuntime`, `ContextRuntime`, participant-aware sessions, nested YAML config, and initial plugin lifecycle boundaries.              |
| 2026-08 | Added explicit separation between participant transport identity, session-scoped participant ID, temporary user identity, and Persona-resolved user identity. |
| 2026-08 | Added application-, participant-, and runtime-time separation so persistence, user timezone context, and realtime temporal alignment use independent time semantics. |
| 2026-08 | Added creation-date session storage using `sessions/YYYY-MM-DD/<session_id>/` while keeping the session creation date immutable across long-running sessions. |

### 🧭 TODO

| Priority | Task | Stage |
| :------- | :--- | :---: |
| 🔸 | Complete multi-user streaming identity management with participant-level speaker tracking, face tracking, concurrent Persona resolution, conflict handling, and per-user routing. | ⏳ In Progress |
| 🔹 | Improve provider runtime capabilities with fallback chains, retry policies, cost estimation, provider health checks, and model compatibility validation. | 🧩 Planned |
| 🔹 | Solve the cocktail-party problem for multi-speaker scenarios, including speaker separation, speaker tracking, overlapping speech handling, and per-user context routing. | 🧩 Planned |
| 🔹 | Add user upload lifecycle management, including temporary session storage, identity-aware persistence, artifact indexing, and cleanup policies. | 🧩 Planned |

## Prompt & Context

### ✅ DONE

| Date    | Milestone | Notes |
| :------ | :-------- | :---- |
| 2026-05 | **System Prompt / Runtime Prompt Split** | Static content such as avatar introduction, interaction method, persona, and global behavior rules is kept in the system prompt for better prefix-cache reuse. |
| 2026-05 | **Runtime Context Injection** | Dynamic per-turn information such as memory, current time, plan, reflection, and turn-level behavior rules is injected after the user query. |
| 2026-05 | **Synthetic Tool Runtime Context Mode** | Added a model-compatible way to inject runtime context using synthetic tool-call / tool-output frames. |
| 2026-05 | **Interaction Method Awareness** | Runtime prompt understands whether the current room supports text, voice, audio output, video input, and video output. |
| 2026-05 | **Browser Timezone Integration** | Web demo passes browser timezone, locale, and UTC offset through LiveKit participant metadata so AlphaAvatar can build natural login time context. |
| 2026-08 | **Provider-neutral Model Input** | Added AlphaAvatar-owned text, image, audio, temporal, function-call, and function-output model input structures with input-type-specific renderers and provider-boundary conversion. |
| 2026-08 | **Structured Temporal Input Context** | Current multimodal input is rendered as a time-aligned structured timeline containing speech, visual evidence, source-state transitions, pauses, perception gaps, and direct inputs. |
| 2026-08 | **Runtime Capability Awareness** | Added typed internal capability metadata for Memory and Persona and injects currently enabled capabilities into the stable Avatar system prompt. |
| 2026-08 | **Participant-scoped Time Context** | Runtime context can represent independent current-time and timezone views for multiple participants without coupling persistence timestamps to user-facing time. |

### 🧭 TODO

| Priority | Task | Stage |
| :------- | :--- | :---: |
| 🔸 | Add adaptive prompt budgeting and context selection based on modality, model capability, context size, latency target, and active participant. | ⏳ In Progress |
| 🔸 | Add response style adaptation based on interaction mode, such as shorter voice responses, richer text responses, and visual grounding when video input exists. | ⏳ In Progress |
| 🔹 | Add country / location hint support based on browser timezone, locale, and optional IP-based geo hints, while treating them as soft signals. | 🧩 Planned |
| 🔹 | Add runtime context compression to avoid long dynamic prompts when memory, RAG, reflection, and plans become large. | 🧩 Planned |
| 🔹 | Add prompt versioning and prompt evaluation for system prompt, runtime prompt, memory extraction prompt, and persona extraction prompt. | 🧩 Planned |
| 🔹 | Add model-specific prompt adapters for OpenAI, Gemini, Claude, local models, and small edge models. | 🧩 Planned |

---

## Runtime

### ✅ DONE

| Date    | Milestone                            | Notes |
| :------ | :----------------------------------- | :---- |
| 2026-07 | **AvatarRuntime Composition**        | Added `AvatarRuntime` as the session-scoped composition root for `SessionRuntime`, `ContextRuntime`, `PerceptionRuntime`, and `InferenceExecutor`. |
| 2026-07 | **Simplified Plugin Lifecycle**      | Runtime dependencies are injected during plugin construction, while `on_session_start()` and `on_session_stop()` only manage lifecycle work. |
| 2026-07 | **Producer / Consumer Orchestration**| Perception consumers start before RTC producers, while producers stop before consumers to preserve clean full-duplex lifecycle boundaries. |
| 2026-07 | **AlphaAvatar Inference Runtime**    | Added Worker-owned `InferenceRuntime`, session-scoped `InferenceExecutor`, Unix domain socket IPC, and persistent runner processes independent of LiveKit Agent inference internals. |
| 2026-07 | **Isolated Inference Runners**       | VAD, speaker vector, speaker attributes, face analysis, and all Persona, Memory, and MCP VDB workloads now run in independent persistent processes. |
| 2026-08 | **Immutable Turn Snapshots** | Added turn-scoped immutable perception snapshots so retries and tool follow-ups reuse the original input boundary instead of observing later realtime state. |
| 2026-08 | **Staged Concurrent Lifecycle** | Runtime plugins now start and stop in dependency-safe stages, execute independent lifecycle work concurrently, roll back failed startup, and stop producers before consumers. |
| 2026-08 | **Runtime Capability Metadata** | Added reusable capability contracts that allow internal runtime components to expose model-facing semantic capabilities independently of concrete plugin implementations. |

### 🧭 TODO

| Priority | Task | Stage |
| :------- | :--- | :---: |
| 🔸 | Remove remaining `livekit.agents` runtime ownership by migrating native turn commitment, final Assistant delivery, interruption, and session lifecycle into AlphaAvatar-owned runtime and entrypoint adapters. | ⏳ In Progress |
| 🔹 | Complete runtime lifecycle contracts with consistent `aclose`, health checks, explicit resource ownership, worker recovery, and runtime health observability. | 🧩 Planned |
| 🔹 | Add session replay and audit tooling based on turns, provider traces, memory events, and runtime status events. | 🧩 Planned |
| 🔹 | Add richer error handling and recovery policies across model calls, tool invocation, plugin initialization, channel adapters, and realtime media streams. | 🧩 Planned |
| 🔹 | Enrich the logging and tracing system with per-room, per-session, per-participant, per-user, per-turn, and per-provider-task prefixes. | 🧩 Planned |
| 🔹 | Add version control and compatibility checks for each plugin package, provider integration, config schema, and runtime protocol. | 🧩 Planned |
| 🔹 | Add latency profiling and optimization across the voice pipeline, provider calls, tool invocation, memory retrieval, RAG, MCP, status feedback, and channel adapters. | 🧩 Planned |

## Vision

### ✅ DONE

| Date    | Milestone                            | Notes |
| :------ | :----------------------------------- | :---- |
| 2026-05 | **Vision Input Module**              | Added a dedicated `avatar/vision` module for real-time visual context handling, session-aware activation, and vision plugin integration. |
| 2026-05 | **Sampled Video Frame Support**      | Supports sampled-frame visual input from real-time video streams instead of continuously sending every frame to the model. |
| 2026-05 | **Runtime Visual Context Injection** | Injects current sampled frames into the temporary model-facing context, strips stale historical visuals, and adds placeholders when needed. |
| 2026-07 | **Shared Perception Consumption**    | Sampled Frame Vision consumes asynchronous observation windows from `PerceptionRuntime` instead of subscribing to RTC tracks directly. |
| 2026-07 | **Late-bound Annotated Frames**      | Vision snapshots retain shared observations and resolve annotated frame views when visual context is injected into the model. |
| 2026-08 | **Stateless Visual Selection** | Removed the stateful Sampled Frame Vision runtime and replaced it with pure `VisualFrameSelector` selection over immutable aligned perception. |
| 2026-08 | **Temporal Visual Grounding** | Visual evidence now preserves temporal slices and authoritative start/end source state so historical frames cannot be mistaken for a currently active camera or screen. |

### 🧭 TODO

| Priority | Task | Stage |
| :------- | :--- | :---: |
| 🔸 | Improve visual frame sampling policy based on interaction state, user speech, motion, camera activity, and model demand. | ⏳ In Progress |
| 🔸 | Add user-facing visual grounding behavior, such as explicitly stating when the assistant can or cannot see the current camera frame. | ⏳ In Progress |
| 🔹 | Add screen sharing visual input support for debugging, document reading, and workflow assistance. | 🧩 Planned |
| 🔹 | Add multi-user visual scene understanding, including face tracking, active speaker alignment, and per-user context routing. | 🧩 Planned |
| 🔹 | Expand visual-history retrieval with object, event, identity, time-range, screenshot, and whiteboard search. | 🧩 Planned |
| 🔹 | Add visual privacy controls, allowing users to enable, disable, inspect, or discard visual context per session. | 🧩 Planned |
| 🔹 | Add multimodal evaluation for visual grounding accuracy, latency, and hallucination resistance. | 🧩 Planned |

---

# AlphaAvatar Plugins

## 🟢 STATUS

### ✅ DONE

| Date    | Milestone                          | Notes                                                                                                                                                             |
| :------ | :--------------------------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2026-05 | **Status Plugin Architecture**     | Added a replaceable status plugin with policy, renderer, and sink implementations while keeping the core protocol in `alphaavatar.agents.status`.                 |
| 2026-05 | **Intermediate Status Lifecycle**  | Added status events such as `READY`, `THINKING`, `TOOL_START`, `TOOL_PROGRESS`, `TOOL_END`, `TOOL_ERROR`, and `FINALIZING` for real-time interaction feedback.    |
| 2026-05 | **LLM + Tool Status Feedback**     | Added delayed thinking after user input, post-tool finalizing feedback, tool start monologues, and graceful tool error fallback for DeepResearch, RAG, and MCP.   |
| 2026-05 | **Template-based Status Renderer** | Moved status response templates out of Python code into language-specific template files selected by `type + source + stage`, with multiple randomized templates. |
| 2026-05 | **Multi-sink Status Delivery**     | Supports logger sink, LiveKit action event sink, and room-type-aware text/voice delivery with interruptible status speech that does not enter chat context.       |

### 🧭 TODO

| Priority | Task                                                                                                                                            |     Stage     |
| :------- | :---------------------------------------------------------------------------------------------------------------------------------------------- | :-----------: |
| 🔸       | Add structured status trace logs showing whether an event was emitted, blocked by policy, rendered, delivered, skipped by sink, or interrupted. | ⏳ In Progress |
| 🔸       | Make `TOOL_END` useful for UI action timelines while keeping it silent for text/voice by default.                                               | ⏳ In Progress |
| 🔹       | Add weighted status templates so common phrases appear more often while preserving variation.                                                   |   🧩 Planned  |
| 🔹       | Add template variables for safe metadata such as `url_count`, `tool_count`, `document_count`, and `data_source`.                                |   🧩 Planned  |
| 🔹       | Add per-user status verbosity preferences, such as quiet, normal, and verbose modes.                                                            |   🧩 Planned  |
| 🔹       | Add status timeline support for frontend UI, including thinking, searching, reading, tool execution, and result organization.                   |   🧩 Planned  |
| 🔹       | Add tool progress events for long-running DeepResearch, RAG indexing, and MCP parallel tool execution.                                          |   🧩 Planned  |
| 🔹       | Add turn-level status metrics such as first-status latency, first-answer latency, tool count, status count, and interruption count.             |   🧩 Planned  |

---

## 🎯 INTERACTION ROUTER

### ✅ DONE

| Date    | Milestone                           | Notes |
| :------ | :---------------------------------- | :---- |
| 2026-07 | **Interaction Router Runtime**      | Added a plugin-based processing runtime between raw perception streams and derived interaction streams. |
| 2026-07 | **Audio Activity Processing**       | Added AlphaAvatar-native Silero VAD processing with pre-roll, bounded queues, speech boundaries, and publication into `PerceptionRuntime.speech`. |
| 2026-07 | **Speech Transcription Processing** | Added `openai_segment` and `openai_realtime` STT paths with normalized transcription events and a temporary LiveKit turn-pipeline bridge. |
| 2026-08 | **Output Processing Runtime**       | Extended the Router into speech synthesis and playback-aware transcript synchronization while preserving transport-independent cancellation and output ordering. |

### 🧭 TODO

| Priority | Task | Stage |
| :------- | :--- | :---: |
| 🔸 | Move user-turn commitment and response decisions from the temporary LiveKit bridge into the Interaction Router. | ⏳ In Progress |
| 🔸 | Remove duplicate LiveKit VAD processing and the temporary STT bridge after native turn management is complete. | ⏳ In Progress |
| 🔸 | Detect whether the current input is directed to the Avatar or should be ignored. | ⏳ In Progress |
| 🔸 | Route inputs into answer, ignore, clarify, tool workflow, or status-only paths. | ⏳ In Progress |
| 🔹 | Select early status feedback based on user intention, task type, and interaction mode. | 🧩 Planned |
| 🔹 | Support multi-user routing for voice, visual, and group conversation scenarios. | 🧩 Planned |

---

## 😊 CHARACTER

### ✅ DONE

| Date    | Task                                     |
| :------ | :--------------------------------------- |
| 2025-12 | Integrated AIRI Live2D into AlphaAvatar. |

### 🧭 TODO

| Priority | Task                                                                                                                    |    Stage   |
| :------- | :---------------------------------------------------------------------------------------------------------------------- | :--------: |
| 🔹       | Improve avatar synchronization between voice output, Live2D motion, facial expression, and conversation state.          | 🧩 Planned |
| 🔹       | Connect status events to avatar animation states, such as thinking, searching, listening, speaking, and error recovery. | 🧩 Planned |
| 🔹       | Add persona-aware avatar expression control based on emotion, conversation topic, and user relationship.                | 🧩 Planned |

---

## 🧠 MEMORY

### ✅ DONE

| Date    | Milestone                                   | Notes |
| :------ | :------------------------------------------ | :---- |
| 2025-09 | **Automatic Memory Extraction v1**          | Built on Memory Client, enabling memory capture and retrieval across Assistant–User, Assistant–Tools, and Assistant self-memory. |
| 2026-01 | **Automatic Assistant–Tools Extraction v1** | Added Assistant–Tools memory in user sessions for DeepResearch and RAG plugins. |
| 2026-04 | **Automatic Assistant–Tools Extraction v2** | Designed differentiated prompts for self-memory, shared Assistant–User memory, and shared Assistant–Tools memory. |
| 2026-04 | **Local Memory Storage and Retrieval**      | Supports local memory storage and retrieval through LanceDB. |
| 2026-05 | **Runtime Memory Injection**                | Memory is treated as dynamic per-turn context instead of static system prompt content to improve prefix-cache hit rate. |
| 2026-06 | **Graph-aware Memory Foundation**           | Added graph-based memory association across sessions, users, entities, tools, and future multimodal observations. Includes multi-object MemoryItem, session-scoped graph nodes, alias-ready lookup, and LanceDB graph-node retrieval. |
| 2026-07 | **Online ENV Memory Extraction**            | Added periodic ENV memory extraction from ordered live visual observation windows through configurable multimodal provider tasks. |
| 2026-07 | **Annotated Visual Evidence**               | ENV extraction prefers annotated JPEG views and falls back to raw visual evidence without persisting runtime frame payloads. |
| 2026-07 | **ENV Memory Consolidation**                | Added `MemoryType.ENV` updates and final fusion with conversation and tool memory during the session lifecycle. |
| 2026-07 | **Asynchronous ENV Scheduler**              | Separated fast perception capture and cursor commits from serialized multimodal extraction, with pending-batch merging, bounded retries, and session-stop draining. |
| 2026-07 | **Memory VDB Runtime Migration**            | Migrated Memory LanceDB and Qdrant workloads from LiveKit’s shared inference executor to dedicated AlphaAvatar runner processes. |
| 2026-08 | **Audiovisual ENV Memory**                  | ENV Memory now combines sampled visual observations with continuous raw environmental audio while excluding speech-derived and direct-user input streams from environment evidence. |
| 2026-08 | **Adaptive ENV Memory Scheduling**          | Periodic ENV updates defer boundaries during active speech, commit at complete speech boundaries when possible, and enforce a bounded maximum defer duration. |
| 2026-08 | **Memory VDB Backend Parity**               | Unified LanceDB and Qdrant Memory runner behavior and persistence contracts. |
| 2026-08 | **Structured Memory Timestamps**            | Memory items now persist structured `created_at` timestamps instead of user-facing session-time strings, enabling reliable ordering across sessions and timezones. |

### 🧭 TODO

| Priority | Task | Stage |
| :------- | :--- | :---: |
| 🔸 | Improve ENV memory retrieval with object-, event-, identity-, location-, and time-aware visual-history queries. | ⏳ In Progress |
| 🔸 | Refine ENV graph-node extraction so only concrete observed entities become graph anchors. | ⏳ In Progress |
| 🔹 | Add `node_merge` for graph node canonicalization, including alias conflict handling, duplicate node merging, scoped-local-to-canonical mapping, and optional VDB reindexing. | 🧩 Planned |
| 🔹 | Decompose Memory into independently registered Conversation, Environment, Tool, Graph, and future capability modules under a shared Memory runtime contract. | 🧩 Planned |
| 🔹 | Add cross-window event consolidation and duplicate suppression for long-running sessions. | 🧩 Planned |
| 🔹 | Allow users to actively query, recall, correct, or delete specific memories on demand. | 🧩 Planned |
| 🔹 | Add multi-user memory isolation when multiple users are interacting in the same session. | 🧩 Planned |
| 🔹 | Extend event-driven memory triggers beyond current periodic/user-turn ENV updates to reflection, planning, behavior adaptation, and status-aware interaction events. | 🧩 Planned |
| 🔹 | Add omni-memory updates from text, voice, images, video, tools, files, and external workspaces. | 🧩 Planned |
| 🔹 | Expand graph-aware retrieval to richer relationships, temporal events, aliases, and long-term user goals. | 🧩 Planned |
| 🔹 | Add memory confidence, source attribution, and conflict resolution. | 🧩 Planned |

## 🧬 PERSONA

### ✅ DONE

| Date    | Milestone | Notes |
| :------ | :-------- | :---- |
| 2025-10 | **Automatic User Profile Extraction v1** | Generates personalized, context-aware responses based on conversation history. |
| 2025-11 | **Speaker Verification** | Added speech-based profiling through speaker vector extraction and identification. |
| 2026-05 | **Runtime State Tracking** | Added deterministic user runtime state, including current timezone, login time, session ID, room type, last timezone, last login time, and login count. |
| 2026-05 | **Runtime State Markdown Storage** | Runtime state is stored locally as markdown instead of being mixed into LLM-extracted profile vectors. |
| 2026-05 | **Temporary Persona Replacement** | Runtime-only temporary persona can be replaced by the resolved real user profile while preserving current session runtime state. |
| 2026-05 | **Identity-aware UserPath Binding** | Persona local storage follows user identity changes through mutable `UserPath`. |
| 2026-06 | **Realtime Face Detection** | Added realtime face detection from camera input through the Persona visual identity pipeline. |
| 2026-06 | **Face-based Identity Support** | Integrated face vectors with Persona identity resolution, local cache matching, and VDB-backed persistence. |
| 2026-07 | **Perception-based FaceStream** | FaceStream consumes shared visual observations instead of subscribing directly to LiveKit tracks. |
| 2026-07 | **Face Annotation Rendering** | Face detections are published as `EnvAnnotation` records and rendered into alternate annotated payload views. |
| 2026-07 | **Perception-based SpeakerStream** | Speaker recognition now consumes routed speech observations from `PerceptionRuntime.speech` instead of depending on LiveKit VAD segmentation. |
| 2026-07 | **Rolling Speaker Inference** | Added rolling speech windows, configurable inference cadence, reduced speaker-attribute frequency, and latest-window queue behavior. |
| 2026-07 | **Isolated Persona Inference** | Speaker vector, speaker attributes, face analysis, and Persona VDB operations now run through independent AlphaAvatar inference processes. |
| 2026-08 | **Structured Persona Time Semantics** | Persona runtime state and profile fields now keep structured login/update datetimes while user-facing rendering converts them into each participant's current timezone. |
| 2026-08 | **Persona Capability Metadata** | Profile, speaker-recognition, and face-recognition capabilities are declared at the abstract component level and automatically exposed to the Avatar system prompt. |
| 2026-08 | **Participant-aware Identity Foundation** | Persona identity resolution updates resolved user identity while preserving stable participant identity and shared runtime references. |

### 🧭 TODO

| Priority | Task | Stage |
| :------- | :--- | :---: |
| 🔸 | Support persona visualization interface for profile inspection and correction. | ⏳ In Progress |
| 🔸 | Add multi-user profile management for concurrent interactions. | ⏳ In Progress |
| 🔸 | Add real-time profile retrieval and profile switching during active conversation. | ⏳ In Progress |
| 🔹 | Add cross-platform identity linking for the same user across web, desktop, WhatsApp, and future channels. | 🧩 Planned |
| 🔹 | Add user-confirmed identity merge and identity conflict resolution. | 🧩 Planned |
| 🔹 | Add persona privacy controls, allowing users to inspect, edit, export, or delete profile fields. | 🧩 Planned |
| 🔹 | Add event triggers for profile updates, reflection cycles, and planning refresh. | 🧩 Planned |
| 🔹 | Add multi-user face tracking, active speaker alignment, and per-user visual context routing. | 🧩 Planned |

## 💡 REFLECTION

### ✅ DONE

| Date | Milestone | Notes |
| :--- | :-------- | :---- |
| - | - | - |

### 🧭 TODO

| Priority | Task | Stage |
| :------- | :--- | :---: |
| 🔸 | Build Reflection Plugin Alpha for summarizing recent memories, tool results, failures, repeated user needs, and behavioral improvements. | 🧩 Planned |
| 🔹 | Add offline reflection cycles after session exit. | 🧩 Planned |
| 🔹 | Add online lightweight reflection during long sessions. | 🧩 Planned |
| 🔹 | Feed reflection results into memory, behavior, and planning plugins. | 🧩 Planned |

---

## 📅 PLANNING

### ✅ DONE

| Date | Milestone | Notes |
| :--- | :-------- | :---- |
| - | - | - |

### 🧭 TODO

| Priority | Task | Stage |
| :------- | :--- | :---: |
| 🔸 | Build Planning Plugin Alpha based on memory, persona, reflection, reminders, and external tool results. | 🧩 Planned |
| 🔹 | Add short-term task tracking for ongoing user requests. | 🧩 Planned |
| 🔹 | Add long-term goal tracking based on user memory and profile. | 🧩 Planned |
| 🔹 | Integrate planning outputs with Notion, Calendar, Todoist, or other task systems. | 🧩 Planned |

---

## ⚙️ BEHAVIOR

### ✅ DONE

| Date | Milestone | Notes |
| :--- | :-------- | :---- |
| - | - | - |

### 🧭 TODO

| Priority | Task | Stage |
| :------- | :--- | :---: |
| 🔸 | Build Behavior Plugin Alpha for response style, workflow selection, tool-use policy, and proactive assistance rules. | 🧩 Planned |
| 🔹 | Add global behavior rules and turn-level behavior rules. | 🧩 Planned |
| 🔹 | Add user-configurable behavior preferences. | 🧩 Planned |
| 🔹 | Add safe fallback behavior when tools fail or runtime context is incomplete. | 🧩 Planned |

---

# Tools Plugins

## 🔍 DeepResearch

### ✅ DONE

| Date    | Milestone                          | Notes                                                                                                                  |
| :------ | :--------------------------------- | :--------------------------------------------------------------------------------------------------------------------- |
| 2025-12 | **Tavily API Integration v1**      | Supports fast online retrieval, deep search, scraping, and webpage-to-PDF conversion.                                  |
| 2026-05 | **Status-aware DeepResearch Tool** | Emits `TOOL_START` status with optional model-generated monologue and supports `TOOL_ERROR` fallback through ToolBase. |

### 🧭 TODO

| Priority | Task                                                                                                                           |    Stage   |
| :------- | :----------------------------------------------------------------------------------------------------------------------------- | :--------: |
| 🔹       | Add richer `TOOL_PROGRESS` updates during long research workflows, such as searching, extracting, reading, and synthesizing.   | 🧩 Planned |
| 🔹       | Retrieve all accessible webpage links under a specified webpage and store them in a specific folder for RAG indexing.          | 🧩 Planned |
| 🔹       | Add automatic summary metadata for downloaded pages, PDFs, and search results so memory and RAG can reference them later.      | 🧩 Planned |
| 🔹       | Make DeepResearch outputs identity-aware through `UserPath`, so downloaded artifacts are stored in the correct user workspace. | 🧩 Planned |

---

## 📖 RAG

### ✅ DONE

| Date    | Milestone                                 | Notes                                                                                                                                        |
| :------ | :---------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------- |
| 2026-01 | **RAG Anything Integration**              | Supports query and indexing based on documents and pages from DeepResearch plugin.                                                           |
| 2026-05 | **UserPath-aware RAG Workspace**          | RAG local workspace dynamically follows user identity changes through mutable `UserPath`.                                                    |
| 2026-05 | **RAG Initialization Waiting**            | Added `_ensure_loaded()` so query and indexing wait for RAGAnything initialization.                                                          |
| 2026-05 | **Temporary + Current RAG Query Support** | Keeps previous temporary RAG instances as fallback after user identity resolution, while new indexing writes to the resolved user workspace. |
| 2026-05 | **LLM-friendly RAG Query Output**         | RAG query returns structured markdown sections instead of raw JSON for easier LLM consumption.                                               |
| 2026-05 | **Status-aware RAG Tool**                 | Emits `TOOL_START` status with optional model-generated monologue and supports `TOOL_ERROR` fallback through ToolBase.                       |

### 🧭 TODO

| Priority | Task                                                                                                                       |     Stage     |
| :------- | :------------------------------------------------------------------------------------------------------------------------- | :-----------: |
| 🔸       | Add robust temp-to-real RAG migration policy after identity resolution.                                                    | ⏳ In Progress |
| 🔸       | Add richer `TOOL_PROGRESS` updates during indexing, such as parsing, chunking, embedding, saving, and indexing completion. | ⏳ In Progress |
| 🔹       | Allow folder indexing and workspace-scoped retrieval across different data sources.                                        |   🧩 Planned  |
| 🔹       | Add structured metadata for different data sources, including directories, source type, creation time, and user ownership. |   🧩 Planned  |
| 🔹       | Add RAG result reranking and answer synthesis across current user RAG, temporary session RAG, and global knowledge.        |   🧩 Planned  |
| 🔹       | Allow AlphaAvatar to index and retrieve pre-written Skills for more efficient command execution.                           |   🧩 Planned  |

---

## 🧰 MCP

### ✅ DONE

| Date    | Milestone                             | Notes                                                                                                                    |
| :------ | :------------------------------------ | :----------------------------------------------------------------------------------------------------------------------- |
| 2026-02 | **MCP Host Integration**              | Integrated MCP Host as an MCP plugin for AlphaAvatar, supporting MCP registration, tool search, and parallel invocation. |
| 2026-05 | **Runner-level MCP Initialization**   | Initializes MCP servers and tool registry once per LiveKit worker instead of once per session.                           |
| 2026-05 | **LanceDB-backed MCP Tool Retrieval** | Stores MCP tool metadata in LanceDB and supports top-k semantic tool search from agent queries.                          |
| 2026-05 | **MCP Tool Runtime Robustness**       | Adds stable tool IDs, agent-friendly tool usage hints, argument validation, hybrid reranking, and server reconnect.      |
| 2026-05 | **Status-aware MCP Tool**             | Emits `TOOL_START` status with optional model-generated monologue and supports `TOOL_ERROR` fallback through ToolBase.   |
| 2026-07 | **MCP VDB Runtime Migration**         | Migrated MCP LanceDB and Qdrant retrieval workloads to dedicated AlphaAvatar inference runner processes. |

### 🧭 TODO

| Priority | Task                                                                                                                                            |     Stage     |
| :------- | :---------------------------------------------------------------------------------------------------------------------------------------------- | :-----------: |
| 🔸       | Integrate Notion MCP.                                                                                                                           | ⏳ In Progress |
| 🔸       | Add richer `TOOL_PROGRESS` updates during parallel MCP execution, including tool count, completed count, failed count, and slow tool detection. | ⏳ In Progress |
| 🔹       | Support global MCP + user-level MCP routing for OAuth-based tools such as Gmail, Calendar, Todoist, and Notion.                                 |   🧩 Planned  |
| 🔹       | Make `search_tools()` support dynamic `top_k`, server filters, and tool category filters.                                                       |   🧩 Planned  |
| 🔹       | Add compact/raw output modes for `call_tools()` to control long tool results.                                                                   |   🧩 Planned  |
| 🔹       | Add `refresh_tools` operation to reload MCP tools without restarting the worker.                                                                |   🧩 Planned  |
| 🔹       | Redact sensitive fields from MCP logs, including tokens, API keys, passwords, and authorization headers.                                        |   🧩 Planned  |
| 🔹       | Add MCP permission model for user-scoped tools and external account authorization.                                                              |   🧩 Planned  |

---

# Channels

## 🌐 Web Demo

### ✅ DONE

| Date    | Milestone | Notes |
| :------ | :-------- | :---- |
| 2026-04 | **LiveKit Web Demo v1** | Built realtime browser demo with voice, text chat, camera preview, agent audio/video stage, and session controls. |
| 2026-05 | **Browser Timezone Metadata** | Sends browser timezone, locale, and UTC offset to AlphaAvatar through participant metadata. |
| 2026-05 | **Room / Session Modality Awareness** | Web session metadata helps AlphaAvatar infer available text, voice, and video interaction modes. |

### 🧭 TODO

| Priority | Task | Stage |
| :------- | :--- | :---: |
| 🔸 | Add user-facing persona and memory inspection panels. | ⏳ In Progress |
| 🔹 | Add upload UI for documents, folders, images, and URLs. | 🧩 Planned |
| 🔹 | Add screen sharing and visual grounding support. | 🧩 Planned |
| 🔹 | Add demo session debugging panel for room metadata, participant metadata, agent status, and tool status. | 🧩 Planned |
| 🔹 | Add user login and persistent identity binding. | 🧩 Planned |

---

## WhatsApp

### ✅ DONE

| Date    | Milestone | Notes |
| :------ | :-------- | :---- |
| 2026-02 | **WhatsApp Channel Integration v1** | Built the initial WhatsApp channel based on the Baileys driver + Python bridge architecture. |
| 2026-02 | **QR Login & Persistent Session Support** | Supports WhatsApp authentication through QR code login with persistent local session storage. |
| 2026-04 | **Whitelist Support** | Supports using a whitelist on WhatsApp to restrict users from accessing AlphaAvatar. Groups are blocked by default. |

### 🧭 TODO

| Priority | Task | Stage |
| :------- | :--- | :---: |
| 🔸 | LiveKit streaming integration. | ⏳ In Progress |
| 🔸 | Voice / image / media support. | ⏳ In Progress |
| 🔹 | Meta Cloud API driver. | 🧩 Planned |
| 🔹 | Twilio driver. | 🧩 Planned |
| 🔹 | Multi-driver runtime selection. | 🧩 Planned |
| 🔹 | Group chat support with multi-user identity routing. | 🧩 Planned |
| 🔹 | Cross-channel identity binding between WhatsApp users and web/demo users. | 🧩 Planned |

---

# NEXT STEPS

| Quarter | Focus | Expected Outcome |
| :------ | :---- | :--------------- |
| Q3-2026 | Perception Runtime Hardening | Add source-aware retention, payload pruning, backpressure, consumer-lag observability, annotation fusion, multi-source alignment, and long-session health policies. |
| Q3-2026 | ENV Memory Retrieval | Add richer object-, event-, identity-, sound-, location-, and time-aware audiovisual history retrieval. |
| Q3-2026 | Native Interaction & LiveKit Decoupling | Move turn commitment, response routing, Assistant delivery, interruption, and session ownership into AlphaAvatar and remove remaining temporary `livekit.agents` VAD/STT/turn compatibility paths. |
| Q3-2026 | Notion MCP Integration | Use Notion as an external long-term workspace for notes, memory summaries, plans, and user knowledge. |
| Q3-2026 | RAG Workspace Evolution | Add data-source scoped retrieval, metadata-aware indexing, temp-to-real RAG migration policy, and skill retrieval. |
| Q4-2026 | Reflection Plugin Alpha | Build autonomous self-analysis from memory, persona, tool results, status traces, and repeated user interaction patterns. |
| Q4-2026 | Reminder & Calendar Foundation | Enable reminders, follow-ups, recurring plans, and schedule-aware assistance through Calendar / Todoist integrations. |
| Q4-2026 | Proactive Assistant Loop | Combine perception, memory, persona, interaction routing, reflection, planning, tools, and status feedback into proactive personal assistant workflows. |
