# 🧠 AlphaAvatar Memory Plugin

The Memory Plugin provides persistent conversation, tool, and environment memory for AlphaAvatar.

## 🧩 Module Overview

The plugin is responsible for:

* extracting durable memories from conversations and tool results;
* building ENV memory from live perception observations;
* attaching identity, session, evidence, and graph metadata;
* storing memory records in local or remote vector databases;
* retrieving relevant memories for future interactions.

Memory extraction is divided into independent paths:

```text
Conversation
    └── → Conversation Memory

Tool / RAG / DeepResearch Result
    └── → Tool Memory

Visual or Audio Observation
    └── → ENV Memory
```

Supported memory types include:

| Memory Type    | Description                                                         |
| -------------- | ------------------------------------------------------------------- |
| `Avatar`       | Stable information about the avatar itself                          |
| `Conversation` | User information, preferences, decisions, and interaction history   |
| `Tools`        | Useful results produced by tools, RAG, MCP, or research             |
| `ENV`          | Information extracted from visual or audio environment observations |

## 🌍 ENV Memory

ENV Memory consumes observation windows from `PerceptionRuntime`.

```text
Video / Screen / Audio Observation
                ↓
        PerceptionRuntime
                ↓
       EnvMemoryScheduler
                ↓
   Multimodal ENV Extraction
                ↓
         MemoryType.ENV
```

`EnvMemoryScheduler` manages:

* periodic ENV memory updates;
* updates triggered by user turns;
* resetting the periodic interval after a successful triggered capture;
* fast perception cursor commits;
* serialized model inference;
* pending batch merging and retry handling.

ENV memory is only updated when visual or audio observations are available.

User text does not independently create ENV memory. It is attached only as additional context when real environment observations are present.

```text
Visual / Audio Observation + User Text
                    ↓
             ENV Memory Update

User Text Only
      ↓
No ENV Memory Update
```

Visual observations are sampled before extraction to avoid repeatedly processing similar frames. Raw audio frames are ignored; future audio support should use audio segments or semantic audio events.

Heavy runtime payloads such as video frames and audio buffers are not stored directly as memory records. ENV memory stores extracted text, evidence references, and metadata.

## 🕸️ Storage and Retrieval

Memory records may contain:

* memory text;
* memory type;
* object ownership;
* session and timestamp metadata;
* observation evidence;
* graph nodes and links;
* provider-specific metadata.

Supported storage backends include:

| Backend   | Usage                                |
| --------- | ------------------------------------ |
| `LanceDB` | Local vector storage and retrieval   |
| `Qdrant`  | Remote or self-hosted vector storage |

Memory retrieval supports:

* semantic context search;
* filtering by memory type, session, or object ID;
* graph-node lookup;
* graph-neighbor expansion;
* identity alias resolution.

Graph metadata improves retrieval across related users, speakers, faces, objects, tools, sessions, and events, while memory text remains the primary stored information.

## 🔗 Module Relationships

```text
PerceptionRuntime
    └── → ENV Memory observations

Persona Plugin
    └── → user, face, and speaker identity aliases

RAG / DeepResearch / MCP
    └── → Tool Memory

Memory Plugin
    ├── → Dynamic runtime context
    ├── → Semantic retrieval
    └── → Graph-aware retrieval
```

## 📦 Installation

```bash
pip install alpha-avatar-plugins-memory
```

The plugin is loaded through the AlphaAvatar configuration.
