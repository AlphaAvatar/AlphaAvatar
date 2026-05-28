# 📈 **MAIN GOAL**

> **Build a universal multimodal personal assistant** capable of recognizing users through streaming voice, text, image, and video input.

> It should possess **self-memory**, **persona awareness**, **autonomous reflection**, **planning ability**, **iterative self-evolution**, and **real-time interaction feedback**.

> The assistant will **seamlessly integrate** with mainstream external tools and personal workspaces to solve practical problems efficiently.

---

# Table of contents

* [PLAN OVERVIEW](#plan-overview)
* [Core Function](#core-function)
* [Vision](#vision)
* [Prompt & Runtime Context](#prompt--runtime-context)
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
| 🧠 **Runtime Context**    | Dynamically injects memory, time, plan, reflection, behavior rules, interaction state, and modality information into each model call. | ✅ Implemented |
| 🧬 **User Continuity**    | Maintains user identity, runtime state, persona, memory, and workspace continuity across sessions.                                    | ✅ Implemented |
| 👁️ **Vision Input**      | Supports sampled visual input from real-time video streams and injects current visual context into model calls.                       | ✅ Implemented |
| 🟢 **Status Feedback**    | Emits intermediate feedback during thinking, tool calls, tool errors, and post-tool result organization to reduce perceived latency.  | ✅ Implemented |
| 🎯 **Interaction Router** | Routes user input based on intention, interaction context, and response necessity; may also select early status feedback.             |   🧩 Planned  |
| 💡 **Reflection**         | Generates metacognitive insights from memory, persona, tool usage, failures, and interaction history.                                 |   🧩 Planned  |
| 📅 **Planning**           | Generates short-term tasks, long-term plans, reminders, and follow-up actions from memory, reflection, and tool results.              |   🧩 Planned  |
| ⚙️ **Behavior**           | Controls response style, workflow selection, tool-use policy, and proactive assistance rules.                                         |   🧩 Planned  |
| 🌍 **World Sandbox**      | Enables AlphaAvatar to interact with external virtual environments, code sandboxes, simulated worlds, or apps.                        |   🧩 Planned  |

---

# Core Function

### ✅ DONE

| Date    | Task                                                                                                                                            |
| :------ | :---------------------------------------------------------------------------------------------------------------------------------------------- |
| 2025-10 | Developed a context manager to route real-time updated interaction information to plugin models such as memory and persona.                     |
| 2026-05 | Added mutable user-scoped working directory support through `UserPath`, enabling plugins to follow identity changes dynamically.                |
| 2026-05 | Added temporary-user to real-user identity resolution flow, including deferred temp directory migration and cleanup at session exit.            |
| 2026-05 | Added runtime-aware session context construction based on room type, session mode, modality availability, user metadata, and time context.      |
| 2026-05 | Added LiveKit room binding support for runtime components that need direct room-level access, such as status sinks and data channel publishers. |

### 🧭 TODO

| Priority | Task                                                                                                                                               |     Stage     |
| :------- | :------------------------------------------------------------------------------------------------------------------------------------------------- | :-----------: |
| 🔸       | Support different model interfaces for different plugins, such as memory extraction, persona extraction, reflection, planning, and tool reasoning. | ⏳ In Progress |
| 🔹       | Add multi-user streaming identity management, including speaker diarization, face recognition, and conflict handling.                              |   🧩 Planned  |
| 🔹       | Solve the cocktail-party problem for multi-speaker scenarios, including speaker separation, speaker tracking, and per-user context routing.        |   🧩 Planned  |
| 🔹       | Add user upload lifecycle management: temporary storage during the current session, persistent storage after identity confirmation.                |   🧩 Planned  |
| 🔹       | Add unified plugin lifecycle hooks, such as `on_user_path_changed`, `on_session_exit`, `close`, and `health_check`.                                |   🧩 Planned  |
| 🔹       | Add richer error handling and recovery policies across model calls, tool invocation, plugin initialization, and channel adapters.                  |   🧩 Planned  |
| 🔹       | Enrich the logging system with per-room, per-session, per-user, and per-turn prefixes.                                                             |   🧩 Planned  |
| 🔹       | Add version control and compatibility checks for each plugin package.                                                                              |   🧩 Planned  |
| 🔹       | Add latency profiling and optimization across voice pipeline, tool invocation, memory retrieval, RAG, MCP, status feedback, and channel adapters.  |   🧩 Planned  |

---

# Vision

### ✅ DONE

| Date    | Milestone                            | Notes                                                                                                                                       |
| :------ | :----------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------ |
| 2026-05 | **Vision Input Module**              | Added a dedicated `avatar/vision` module for real-time visual context handling, session-aware activation, and vision plugin integration.    |
| 2026-05 | **Sampled Video Frame Support**      | Supports sampled-frame visual input from real-time video streams instead of continuously sending every frame to the model.                  |
| 2026-05 | **Runtime Visual Context Injection** | Injects current sampled frames into the temporary model-facing context, strips stale historical visuals, and adds placeholders when needed. |

### 🧭 TODO

| Priority | Task                                                                                                                                 |     Stage     |
| :------- | :----------------------------------------------------------------------------------------------------------------------------------- | :-----------: |
| 🔸       | Improve visual frame sampling policy based on interaction state, user speech, motion, camera activity, and model demand.             | ⏳ In Progress |
| 🔸       | Add user-facing visual grounding behavior, such as explicitly stating when the assistant can or cannot see the current camera frame. | ⏳ In Progress |
| 🔹       | Add screen sharing visual input support for debugging, document reading, and workflow assistance.                                    |   🧩 Planned  |
| 🔹       | Add face recognition and face-based identity confirmation integrated with persona and user continuity.                               |   🧩 Planned  |
| 🔹       | Add multi-user visual scene understanding, including face tracking, active speaker alignment, and per-user context routing.          |   🧩 Planned  |
| 🔹       | Add visual memory extraction from important images, screenshots, whiteboards, and camera observations.                               |   🧩 Planned  |
| 🔹       | Add visual privacy controls, allowing users to enable, disable, inspect, or discard visual context per session.                      |   🧩 Planned  |
| 🔹       | Add multimodal evaluation for visual grounding accuracy, latency, and hallucination resistance.                                      |   🧩 Planned  |

---

# Prompt & Runtime Context

### ✅ DONE

| Date    | Milestone | Notes |
| :------ | :-------- | :---- |
| 2026-05 | **System Prompt / Runtime Prompt Split** | Static content such as avatar introduction, interaction method, persona, and global behavior rules is kept in the system prompt for better prefix-cache reuse. |
| 2026-05 | **Runtime Context Injection** | Dynamic per-turn information such as memory, current time, plan, reflection, and turn-level behavior rules is injected after the user query. |
| 2026-05 | **Synthetic Tool Runtime Context Mode** | Added a model-compatible way to inject runtime context using synthetic tool-call / tool-output frames. |
| 2026-05 | **Interaction Method Awareness** | Runtime prompt understands whether the current room supports text, voice, audio output, video input, and video output. |
| 2026-05 | **Browser Timezone Integration** | Web demo passes browser timezone, locale, and UTC offset through LiveKit participant metadata so AlphaAvatar can build natural login time context. |

### 🧭 TODO

| Priority | Task | Stage |
| :------- | :--- | :---: |
| 🔸 | Optimize user prompt construction based on the user’s current input mode: text, voice, camera, screen sharing, uploaded files, or mixed modalities. | ⏳ In Progress |
| 🔸 | Add response style adaptation based on interaction mode, such as shorter voice responses, richer text responses, and visual grounding when video input exists. | ⏳ In Progress |
| 🔹 | Add country / location hint support based on browser timezone, locale, and optional IP-based geo hints, while treating them as soft signals. | 🧩 Planned |
| 🔹 | Add runtime context compression to avoid long dynamic prompts when memory, RAG, reflection, and plans become large. | 🧩 Planned |
| 🔹 | Add prompt versioning and prompt evaluation for system prompt, runtime prompt, memory extraction prompt, and persona extraction prompt. | 🧩 Planned |
| 🔹 | Add model-specific prompt adapters for OpenAI, Gemini, Claude, local models, and small edge models. | 🧩 Planned |

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

| Date | Milestone | Notes |
| :--- | :-------- | :---- |
| - | - | - |

### 🧭 TODO

| Priority | Task | Stage |
| :------- | :--- | :---: |
| 🔸 | Detect whether the current input is directed to the Avatar or should be ignored. | 🧩 Planned |
| 🔸 | Route inputs into answer, ignore, clarify, tool workflow, or status-only paths. | 🧩 Planned |
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

| Date    | Milestone                                   | Notes                                                                                                                            |
| :------ | :------------------------------------------ | :------------------------------------------------------------------------------------------------------------------------------- |
| 2025-09 | **Automatic Memory Extraction v1**          | Built on Memory Client, enabling memory capture and retrieval across Assistant–User, Assistant–Tools, and Assistant self-memory. |
| 2026-01 | **Automatic Assistant–Tools Extraction v1** | Added Assistant–Tools memory in user sessions for DeepResearch and RAG plugins.                                                  |
| 2026-04 | **Automatic Assistant–Tools Extraction v2** | Designed differentiated prompts for self-memory, shared Assistant–User memory, and shared Assistant–Tools memory.                |
| 2026-04 | **Local Memory Storage and Retrieval**      | Supports local memory storage and retrieval through LanceDB.                                                                     |
| 2026-05 | **Runtime Memory Injection**                | Memory is treated as dynamic per-turn context instead of static system prompt content to improve prefix-cache hit rate.          |
| 2026-05 | **Identity-aware Memory Binding**           | Memory object IDs can be updated when a temporary user is resolved into a real user.                                             |

### 🧭 TODO

| Priority | Task                                                                                                                |     Stage     |
| :------- | :------------------------------------------------------------------------------------------------------------------ | :-----------: |
| 🔸       | Allow users to actively query, recall, correct, or delete specific memories on demand.                              | ⏳ In Progress |
| 🔹       | Add multi-user memory isolation when multiple users are interacting in the same session.                            |   🧩 Planned  |
| 🔹       | Add event-driven memory updates for reflection, planning, behavior adaptation, and status-aware interaction traces. |   🧩 Planned  |
| 🔹       | Add omni-memory updates from text, voice, images, video, tools, files, and external workspaces.                     |   🧩 Planned  |
| 🔹       | Add graph-based memory search for relationships, entities, events, and long-term user goals.                        |   🧩 Planned  |
| 🔹       | Add memory confidence, source attribution, and conflict resolution.                                                 |   🧩 Planned  |

---

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

### 🧭 TODO

| Priority | Task | Stage |
| :------- | :--- | :---: |
| 🔸 | Add face-based profiling using facial embedding recognition. | ⏳ In Progress |
| 🔸 | Support persona visualization interface for profile inspection and correction. | ⏳ In Progress |
| 🔸 | Add multi-user profile management for concurrent interactions. | 🧩 Planned |
| 🔹 | Add real-time profile retrieval and profile switching during active conversation. | 🧩 Planned |
| 🔹 | Add cross-platform identity linking for the same user across web, desktop, WhatsApp, and future channels. | 🧩 Planned |
| 🔹 | Add user-confirmed identity merge and identity conflict resolution. | 🧩 Planned |
| 🔹 | Add persona privacy controls, allowing users to inspect, edit, export, or delete profile fields. | 🧩 Planned |
| 🔹 | Add event triggers for profile updates, reflection cycles, and planning refresh. | 🧩 Planned |

---

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
| Q2-2026 | Status + Visual Interaction Polish | Improve perceived latency with status feedback, connect status to UI/Avatar states, and stabilize sampled visual input. |
| Q2-2026 | Interaction Router Foundation | Detect whether input is directed to the Avatar, route requests by interaction type, and choose early status feedback. |
| Q2-2026 | Notion MCP Integration | Use Notion as an external long-term workspace for notes, memory summaries, plans, and user knowledge. |
| Q3-2026 | Reminder & Calendar Foundation | Enable reminders, follow-ups, recurring plans, and schedule-aware assistance through Calendar / Todoist integrations. |
| Q3-2026 | Reflection Plugin Alpha | Build autonomous self-analysis from memory, persona, tool results, status traces, and repeated user interaction patterns. |
| Q3-2026 | Proactive Assistant Loop | Combine memory, persona, reflection, planning, reminders, RAG, MCP, status feedback, and interaction routing into proactive personal assistant workflows. |
| Q3-2026 | RAG Workspace Evolution | Add data-source scoped retrieval, metadata-aware indexing, temp-to-real RAG migration policy, and skill retrieval. |
