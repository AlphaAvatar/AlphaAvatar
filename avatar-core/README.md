# AlphaAvatar Core

## 🧩 Introduction

`avatar-core` provides the transport-agnostic runtime primitives shared across AlphaAvatar.

It defines how multimodal observations are represented, enriched with annotations, published through typed perception streams, aligned on a shared timeline, and selected as consumer-specific windows. The package intentionally remains independent from LiveKit Agents, model providers, and plugin implementations so that RTC adapters, Persona, Memory, Vision, and future multimodal components can evolve without coupling the core runtime to a specific backend.

## 📦 Package Structure

```text
avatar-core/
├── README.md
├── alphaavatar/
│   └── core/
│       ├── __init__.py
│       ├── env/                         # Environment observation envelopes and annotations.
│       │   ├── __init__.py
│       │   ├── annotation.py           # Structured metadata attached to an observation.
│       │   └── observation.py          # Runtime observation envelope for video, audio, screen, and events.
│       ├── media/                       # Backend-independent multimodal payload representations.
│       │   ├── __init__.py
│       │   ├── formats.py              # Payload formats and views such as raw, annotated, and derived.
│       │   ├── payload.py              # Thread-safe multi-representation MediaPayload container.
│       │   └── video.py                # Generic video frame buffers and video payload helpers.
│       ├── perception/                  # Full-duplex perception transport, alignment, and windowing.
│       │   ├── __init__.py
│       │   ├── runtime.py              # PerceptionRuntime entry point and typed stream orchestration.
│       │   ├── stream.py               # Multi-consumer streams with independent cursors and backpressure.
│       │   ├── timeline.py             # Observation–annotation alignment and renderer coordination.
│       │   └── window.py               # Ordered multimodal windows for Memory, Persona, Vision, and routers.
│       └── version.py                  # Package version metadata.
└── pyproject.toml
```

## 🔄 Workflow

External RTC or device adapters first normalize incoming media into AlphaAvatar-owned payloads. `EnvObservation` wraps each payload with identity, source, timestamp, and metadata before publishing it to `PerceptionRuntime`. Persona and other perception modules can attach annotations and produce annotated payload views without overwriting the raw representation. Consumer-specific windows then provide ordered observations to modules such as ENV Memory, Sampled Frame Vision, routers, and future audio or event processors.
