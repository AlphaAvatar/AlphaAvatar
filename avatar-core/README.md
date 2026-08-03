# AlphaAvatar Core

## 🧩 Introduction

`avatar-core` provides the transport-agnostic runtime primitives shared across AlphaAvatar.

It defines how multimodal observations and outputs are represented, published through typed streams, aligned on shared timelines, and consumed independently by runtime modules and transport adapters.

The package intentionally remains independent from LiveKit Agents, model providers, plugin implementations, and frontend protocols. RTC adapters, Persona, Memory, Vision, Router processors, output transports, and future multimodal components can therefore evolve without coupling the core runtime to a specific backend.

The two primary runtime planes are:

```text
PerceptionRuntime
    normalized input observations and annotations

OutputRuntime
    time-aligned status, text, audio, playback, transcript, and control events
```

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
│       │   ├── audio.py                # Generic audio frame representation.
│       │   ├── formats.py              # Payload formats and views such as raw, annotated, and derived.
│       │   ├── payload.py              # Thread-safe multi-representation MediaPayload container.
│       │   └── video.py                # Generic video frame buffers and video payload helpers.
│       ├── output/                      # Time-aligned, transport-independent output runtime.
│       │   ├── __init__.py
│       │   ├── runtime.py              # Output lifecycle, interruption, replacement, and publication.
│       │   ├── schema.py               # Status, text, audio, alignment, playback, transcript, and control events.
│       │   ├── stream.py               # Multi-consumer live output streams with priority interruption.
│       │   └── timeline.py             # Lightweight output history and audio evidence receipts.
│       ├── perception/                  # Full-duplex perception transport, alignment, and windowing.
│       │   ├── __init__.py
│       │   ├── runtime.py              # PerceptionRuntime entry point and typed stream orchestration.
│       │   ├── stream.py               # Multi-consumer streams with independent cursors and backpressure.
│       │   ├── timeline.py             # Observation–annotation alignment and renderer coordination.
│       │   └── window.py               # Ordered multimodal windows for Memory, Persona, Vision, and routers.
│       └── version.py                  # Package version metadata.
└── pyproject.toml
```

## 🔄 Perception Workflow

External RTC or device adapters normalize incoming media into AlphaAvatar-owned payloads.

`EnvObservation` wraps each payload with identity, source, timestamp, and metadata before publishing it to `PerceptionRuntime`. Persona and other perception modules can attach annotations and produce annotated payload views without overwriting the raw representation.

Consumer-specific windows then provide ordered observations to modules such as ENV Memory, Sampled Frame Vision, the Interaction Router, and future audio or event processors.

```text
RTC / Device input
        ↓
AlphaAvatar media payload
        ↓
EnvObservation
        ↓
PerceptionRuntime stream and timeline
        ↓
Persona / Memory / Vision / Router consumers
```

## 📤 Output Workflow

`OutputRuntime` provides the shared output plane for semantic and media output.

It can carry:

- status actions;
- source text chunks;
- compatibility speech requests;
- normalized audio frames;
- text-audio alignment events;
- transport playout feedback;
- delivered transcript chunks;
- interruption and completion controls.

```text
LLM / Status / Tool / Character
        ↓
Source output events
        ↓
OutputRuntime stream and timeline
        ↓
Router processors
        ↓
Audio / transcript / status transport adapters
```

### Output identity

The runtime distinguishes three identifiers:

```text
turn_id
    groups outputs belonging to one interaction turn

output_id
    identifies one complete logical message or utterance

chunk_id
    identifies one source-text, alignment, or transcript segment
```

Multiple outputs may belong to one turn. A new `output_id` may replace another output in the same lane, while additional chunks using the same `output_id` append to the existing logical output.

An interrupted or completed output ID cannot be reopened.

### Output lanes

Output lanes describe semantic purpose rather than transport:

- `ASSISTANT`
- `TRANSIENT`
- `STATUS`
- `CHARACTER`

### Text delivery modes

Source text declares how it participates in delivery:

- `MIRROR`: retained for observability while another system owns user-visible delivery;
- `IMMEDIATE`: may be delivered without waiting for audio;
- `AUDIO_SYNCED`: becomes visible only through transcript events aligned with actual audio playout.

### Interruption semantics

`INTERRUPT` is a priority control event.

On interruption, the runtime:

1. marks the logical output terminal;
2. rejects later source chunks and audio frames for the same `output_id`;
3. discards queued raw audio frames;
4. retains semantic text, alignment, playback, and transcript facts;
5. notifies independent consumers so synthesis, transport queues, UI, and other outputs can stop immediately.

`COMPLETE` remains ordered after produced data because source production finishing does not necessarily mean transport playout has finished.

## ⏱️ Playback and Transcript Alignment

Generated source text and delivered transcript are intentionally separate:

```text
OutputTextChunk
    what AlphaAvatar intended to say

OutputTranscriptChunk
    what the user actually heard
```

Audio transports publish playback feedback such as:

- started;
- progress;
- finished;
- interrupted.

Transcript synchronization processors combine source text, text-audio alignment, and actual played duration to release user-visible transcript incrementally.

When audio is interrupted:

- previously delivered transcript remains;
- unplayed text is not published;
- the source text remains available on the output timeline.

## 🔌 Transport Independence

`avatar-core` does not know about:

- LiveKit rooms or tracks;
- WebRTC APIs;
- TTS, STT, VAD, or LLM providers;
- frontend rendering protocols;
- channel-specific message formats.

Transport adapters subscribe to the core streams and convert AlphaAvatar events into LiveKit, channel, local-device, or future transport output.

This boundary allows AlphaAvatar to remove `livekit.agents` incrementally while retaining LiveKit RTC, or replace LiveKit transport entirely without redesigning the core runtime.
