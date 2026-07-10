# 🧠 Memory Plugin for AlphaAvatar

> Give AlphaAvatar the ability to **remember you, its tools, and its environment** — across conversations, sessions, and time.

---

## 🤔 What is the Memory Plugin?

Imagine talking to an assistant that forgets everything the moment you close the app. Frustrating, right?

The **Memory Plugin** gives AlphaAvatar a persistent memory layer. It can:

- Remember your **preferences, goals, and important facts**
- Recall **past conversations** and previous decisions
- Learn from **tool usage**, research, and retrieved documents
- Build **environment memories** from live visual observations
- Retrieve related memories through **semantic and graph-aware search**

Think of it as AlphaAvatar's long-term notebook — important information is extracted, organized, stored, and brought back when it becomes useful.

---

## 💡 How Does it Work? (Simple Flow)

```text
Conversation / Tool Result / Visual Observation
                    ↓
AlphaAvatar extracts useful memory updates
                    ↓
Runtime adds identity, session, graph, and evidence metadata
                    ↓
Memories are stored in local or remote vector storage
                    ↓
Relevant memories are retrieved in future turns
                    ↓
AlphaAvatar responds with better continuity and grounding
```

Conversation and tool memory work automatically in the background.
Online ENV memory is enabled when a multimodal `env_delta_task` is configured.

---

## ✨ Features

### 🌍 Persistent Memory

AlphaAvatar maintains memories beyond a single chat session.

This includes:

- Things **you** told it
- Important **conversation decisions**
- Results from **MCP, RAG, and DeepResearch**
- Useful observations from the **camera, screen, or surrounding environment**
- Links between people, objects, sessions, tools, and events

### ⚡ Runtime Memory Updates

Memory can update while a session is active instead of waiting until the conversation ends.

Conversation, tool, and ENV memory use separate extraction paths, while the runtime controls timestamps, ownership, evidence, graph structure, and session metadata.

### 👁️ Online ENV Memory

The Memory plugin can consume ordered observation windows from `PerceptionRuntime`.

```text
Video / Screen Observations
            ↓
PerceptionRuntime Window
            ↓
Multimodal ENV Extraction Task
            ↓
EnvMemoryDelta
            ↓
MemoryType.ENV
```

ENV memory prefers annotated visual evidence when available and falls back to raw frames. Heavy runtime payloads such as video frames are never written directly into memory storage.

### 🕸️ Graph-aware Retrieval

Memories can include graph nodes and links for entities such as:

- users
- faces and speakers
- objects
- sessions
- tools
- locations
- events

Graph nodes act as retrieval anchors, while memory text remains the source of truth.

---

## 📦 What Kind of Things Does AlphaAvatar Remember?

| Type | Example |
|------|---------|
| 👤 Personal facts | “My name is Alex and I live in New York.” |
| ❤️ Preferences | “I prefer short, direct answers.” |
| 🗓️ Conversation memory | A decision or topic from an earlier session |
| 🔍 Research results | Findings from a DeepResearch task |
| 📄 Document knowledge | Useful information retrieved through RAG |
| 🛠️ Tool interactions | Results from MCP tools such as Gmail or Notion |
| 👁️ ENV memory | “A person placed a red cup on the desk.” |
| 🕸️ Graph associations | A user, object, tool, and event linked across memories |

---

## 🔧 Installation

```bash
pip install alpha-avatar-plugins-memory
```

The plugin is then loaded through the AlphaAvatar configuration.

To enable online ENV memory, configure a multimodal provider task such as:

```yaml
env_delta_task: memory.env_delta
```

If no ENV extraction task is configured, the rest of the Memory plugin continues to work normally.

---

## 🗄️ How Memories are Stored

AlphaAvatar stores memories as structured records with searchable embeddings and runtime-owned metadata.

Memory records can include:

- memory text
- memory type
- object ownership
- timestamps and session IDs
- evidence references
- graph nodes and links
- additional runtime metadata

### Supported Backends

| Backend | What it Does |
|---------|--------------|
| **LanceDB** | Local vector storage and graph-aware retrieval (default) |
| **Qdrant** | Remote or self-hosted vector storage |
| **Provider Gateway** | Routes extraction tasks to configured LLM or VLM providers |

By default, AlphaAvatar can run with local LanceDB storage. Raw camera frames, audio buffers, and other heavy runtime payloads are not persisted as memory items.

---

## 🔗 How Memory Connects to Other Modules

```text
PerceptionRuntime
      └── → ENV Memory         (visual and future audio observations)

Persona Plugin
      └── → Identity Aliases   (face / speaker / user relationships)

RAG / DeepResearch / MCP
      └── → Tool Memory        (documents, research, and actions)

Memory Plugin
      ├── → Avatar Runtime     (dynamic per-turn context)
      ├── → Graph Retrieval    (entity and relationship lookup)
      ├── → Reflection*        (behavior improvement)
      └── → Planning*          (goals and reminders)

* Planned
```

---

## 🙋 Common Questions

**Q: Does memory work across sessions?**
Yes. Stored memories can be retrieved in later sessions.

**Q: Does ENV memory save my raw camera stream?**
No. Raw runtime frames are not stored as memory records. The configured multimodal model extracts useful environment memories from selected observation windows.

**Q: Is ENV memory always enabled?**
No. It is optional and only runs when `env_delta_task` is configured.

**Q: Can memory distinguish different users?**
Memory supports multi-object ownership and graph aliases. Persona can resolve temporary face or speaker identities to stable users.

**Q: Can I see or delete individual memories?**
Fine-grained inspection, correction, export, and deletion controls are still being developed.

**Q: Is my data private?**
Local LanceDB storage keeps memory data on your own machine unless you configure a remote backend or external model provider.

---

## 🚀 Coming Soon

| Feature | Description |
|---------|-------------|
| 🎤 Audio ENV Memory | Extract useful events and context from continuous audio streams |
| 🔍 Rich Visual-history Search | Search by objects, events, identities, and time ranges |
| 🧩 Multi-annotation Fusion | Combine face, speaker, object, action, and scene annotations |
| 🔒 Memory Privacy Controls | Inspect, edit, export, and delete memories |
| 👥 Stronger Multi-user Memory | Better separation and merging across shared sessions |
| 🧠 Reflection & Planning | Use memory for longer-term behavior improvement and goals |

---

## 📚 Related Links

- [AlphaAvatar ROADMAP — Memory Section](https://github.com/AlphaAvatar/AlphaAvatar/blob/main/ROADMAP.md#-memory)
- [Persona Plugin](https://github.com/AlphaAvatar/AlphaAvatar/blob/main/avatar-plugins/avatar-plugins-persona/README.md)
- [LanceDB Documentation](https://lancedb.com/docs/)
- [Qdrant Documentation](https://qdrant.tech/documentation/)
