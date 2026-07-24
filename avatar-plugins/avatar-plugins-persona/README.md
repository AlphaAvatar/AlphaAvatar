# 🧬 AlphaAvatar Persona Plugin

The Persona Plugin provides user identity recognition and profile management for AlphaAvatar.

## 🧩 Module Overview

The plugin is responsible for:

* identifying users through face and speaker embeddings;
* associating temporary face, speaker, and session identities with stable users;
* maintaining user profile attributes;
* exposing the active user persona to the Avatar Runtime;
* publishing identity-related annotations into `PerceptionRuntime`.

Persona processing is divided into independent paths:

```text
Visual Observation
    └── → Face Recognition

Speech Observation
    └── → Speaker Recognition

Conversation Context
    └── → Persona Profile
```

The resulting identity and profile information can be used by Memory, prompting, retrieval, and other runtime modules.

## 🔍 Identity Processing

### 👁️ Face Recognition

The face stream consumes visual observations from `PerceptionRuntime`.

```text
Video / Screen Observation
            ↓
      PerceptionRuntime
            ↓
       FaceStreamWrapper
            ↓
     FaceAnalysisRunner
            ↓
 Face Embedding and Attributes
            ↓
      User Identity Match
```

Face processing:

* samples frames independently from the shared visual stream;
* performs face detection and embedding extraction;
* matches embeddings against known user profiles;
* updates face attributes and identity associations;
* publishes face annotations back to the original observation;
* optionally renders face bounding boxes into the annotated payload view.

Raw video observations remain unchanged. Rendered overlays are stored in the separate annotated payload view.

### 🎤 Speaker Recognition

The speaker stream consumes routed speech observations rather than subscribing directly to LiveKit audio.

```text
PerceptionRuntime.audio
          ↓
AudioActivityProcessor
          ↓
PerceptionRuntime.speech
          ↓
     Speaker Stream
          ↓
 Speaker Embedding and Match
```

Speaker processing uses rolling speech windows to:

* create speaker embeddings;
* match speech against known users;
* update voice identity attributes;
* associate temporary speaker identities with stable user profiles.

Raw audio frames are used only during runtime processing and are not stored as persona profiles.

## 🧩 Supported Components

| Component               | Input                             | Output                               | Function                                                                                    |
| ----------------------- | --------------------------------- | ------------------------------------ | ------------------------------------------------------------------------------------------- |
| `FaceStreamWrapper`     | `video` and `screen` observations | Face annotations and user matches    | Detects faces, generates embeddings, matches users, and updates face attributes.            |
| `SpeakerStreamWrapper`  | Routed `speech` observations      | Speaker matches and voice attributes | Builds rolling speech windows, generates speaker embeddings, and resolves voice identities. |
| Persona profile runtime | Conversation and identity context | Active persona content               | Maintains user profile information and exposes it to the Avatar Runtime.                    |
| Identity alias handling | Temporary and stable identity IDs | Identity relationships               | Links session, face, speaker, and user identities across runtime modules.                   |

Persona profiles may contain:

* stable user identifiers;
* face and speaker embeddings;
* face and voice attributes;
* profile text;
* temporary identity aliases;
* session and runtime metadata.

## 🔗 Module Relationships

```text
PerceptionRuntime
    ├── → Face observations
    └── → Speech observations

Router Plugin
    └── → Routed speech stream

Persona Plugin
    ├── → Active user identity
    ├── → Persona prompt context
    ├── → Face and speaker annotations
    └── → Identity aliases

Memory Plugin
    └── → User ownership and identity-aware retrieval
```

## 📦 Installation

```bash
pip install alpha-avatar-plugins-persona
```

The plugin is loaded through the AlphaAvatar configuration.
