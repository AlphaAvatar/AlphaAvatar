# 🧬 AlphaAvatar Persona Plugin

The Persona Plugin provides modular user identity recognition, profile extraction, and persistent persona management for AlphaAvatar.

It combines realtime face and speaker recognition with conversation-based user profiling while keeping each capability independently configurable and lifecycle-managed.

## Overview

Persona is organized around a lightweight runtime and independently managed processors:

```text
                     PersonaRuntime
                          │
              ┌───────────┼───────────┐
              │           │           │
          Profiler     Speaker       Face
          Processor    Processor    Processor
              │           │           │
              └───────────┼───────────┘
                          │
                    Persona Cache
                          │
                     PersonaStore
                          │
              ┌───────────┴───────────┐
              │                       │
        Profile / Identity       Runtime State
             Storage                Storage
```

The agent layer only exposes Persona contracts.

Concrete processing, identity resolution, model inference, persistence, and lifecycle management live inside the Persona plugin.

## Features

The plugin provides:

* conversation-based user profile extraction;
* speaker recognition from routed speech observations;
* face recognition from visual observations;
* persistent face and speaker embeddings;
* shared identity resolution across modalities;
* runtime user state tracking;
* configurable Persona processors;
* independent processor lifecycles;
* LanceDB and Qdrant profile storage backends;
* integration with AlphaAvatar `PerceptionRuntime`;
* capability metadata exposed to the Avatar Runtime.

## Processors

Persona currently contains three independent processors.

| Processor           | Input                       | Main responsibility                                    |
| ------------------- | --------------------------- | ------------------------------------------------------ |
| `ProfilerProcessor` | Conversation messages       | Extract and update persistent user profile information |
| `SpeakerProcessor`  | Speech observations         | Speaker recognition and voice attribute extraction     |
| `FaceProcessor`     | Video / screen observations | Face recognition, attributes, and face annotations     |

Each processor implements the shared Persona processor lifecycle:

```text
start()
  ↓
processor runtime
  ↓
stop()
```

Processors can be enabled or disabled independently.

## 👤 Profiler Processor

The Profiler Processor extracts persistent user information from conversation context.

```text
Conversation
     ↓
Persona Cache
     ↓
ProfilerProcessor
     ↓
Profile Delta Extraction
     ↓
User Profile Update
```

Profile updates are delta-based rather than regenerating the complete user profile on every update.

The processor focuses only on profile extraction.

Profile loading and persistence are handled separately by `PersonaStore`, so disabling the Profiler does not disable face or speaker identity recognition.

Typical profile information includes:

* preferred name;
* communication preferences;
* personal preferences;
* constraints;
* goals;
* work and project context;
* relationships;
* user-provided personal information.

Profile fields retain source and update metadata.

## 🎤 Speaker Processor

The Speaker Processor consumes routed speech observations from `PerceptionRuntime`.

```text
RTC Audio
    ↓
Interaction Router
    ↓
Speech Observations
    ↓
SpeakerProcessor
    ↓
Speaker Embedding
    ↓
Identity Resolution
```

Speaker processing uses rolling audio windows and a small bounded inference queue to keep realtime processing independent from audio ingestion.

The processor can:

* generate speaker embeddings;
* resolve speakers against session-local identities;
* search persistent identities;
* update speaker embeddings;
* extract voice-related attributes;
* associate unresolved participants with stable users.

Raw audio is used during realtime processing and is not stored as a Persona profile.

## 👁️ Face Processor

The Face Processor consumes visual observations from `PerceptionRuntime`.

```text
Video / Screen
      ↓
PerceptionRuntime
      ↓
FaceProcessor
      ↓
Face Analysis
      ↓
Face Embedding
      ↓
Identity Resolution
```

The processor performs:

* frame sampling;
* face detection;
* face embedding extraction;
* persistent identity matching;
* face attribute extraction;
* user identity association;
* face annotation publishing.

Realtime face processing uses a small queue and prefers recent frames over accumulated stale frames.

Face annotations are published back through `PerceptionRuntime`.

The original raw visual observation remains unchanged.

## Persona Runtime

`PersonaRuntime` is the top-level Persona runtime plugin.

Its responsibilities are intentionally limited to orchestration and shared state:

* maintain active Persona caches;
* coordinate identity resolution;
* expose current persona content;
* bind configured Persona processors;
* start and stop processors;
* load primary user profiles;
* persist Persona state at shutdown.

Processor-specific inference logic does not belong in `PersonaRuntime`.

## Processor Lifecycle

Persona processors maintain their own lifecycle and runtime resources.

A processor may own:

* asyncio tasks;
* perception consumers;
* bounded inference queues;
* inference state;
* modality-specific caches;
* annotation renderers.

Startup and shutdown are coordinated by `PersonaRuntime`.

Startup failures trigger processor rollback so partially initialized realtime resources are not left running.

Normal shutdown stops processors before final Persona persistence.

## Persona Store

`PersonaStore` provides shared persistence for Persona processors.

```text
PersonaRuntime
      ↓
 PersonaStore
      ├── Profile Details
      ├── Speaker Embeddings
      ├── Face Embeddings
      └── Runtime State
```

This storage layer is independent from the Profiler Processor.

As a result:

```text
Profiler disabled
Speaker enabled
Face enabled
```

is a valid configuration.

Speaker and face recognition can still load and persist identities without conversation profile extraction.

## Vector Storage

Persona currently supports:

* LanceDB
* Qdrant

The selected backend stores searchable profile and identity information such as:

* profile detail items;
* speaker embeddings;
* face embeddings.

The backend is selected through Persona configuration.

Vector storage runs through the shared AlphaAvatar inference runtime rather than blocking the realtime event loop.

## Runtime State

Session-related user state is stored separately from semantic profile information.

Runtime state can include:

* current session ID;
* current timezone;
* current login time;
* room type;
* previous session information;
* login count.

This information is system-observed state and is not generated by the profile extraction model.

## Capabilities

Persona processors expose their capabilities through the AlphaAvatar capability system.

Current capabilities include:

```text
PERSONA_PROFILE
PERSONA_SPEAKER_RECOGNITION
PERSONA_FACE_RECOGNITION
```

Capabilities are derived from the processors that are actually enabled for the runtime.

Disabled processors therefore do not advertise unavailable functionality.

## Installation

```bash
pip install alpha-avatar-plugins-persona
```

The plugin requires the AlphaAvatar runtime and is normally loaded through the AlphaAvatar configuration system.

Python 3.11 is currently supported by the package.

## Development

When extending Persona, prefer adding capability-specific implementation inside the corresponding processor package.

Shared responsibilities should remain outside individual processors:

```text
Identity orchestration → PersonaRuntime
Persistence           → PersonaStore
Profile schema         → profile/
Profiler logic         → processors/profiler/
Speaker logic          → processors/speaker/
Face logic             → processors/face/
```

New processors should implement the Persona processor contract and manage their own runtime resources and lifecycle.

Avoid introducing modality-specific business logic back into the agent layer.
