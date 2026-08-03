# 🎯 AlphaAvatar Interaction Router Plugin

The Interaction Router coordinates real-time input and output processing inside AlphaAvatar.

## 🧭 Module Overview

The Router consumes shared runtime streams and dispatches them through independently managed processors.

Its responsibilities include:

- consuming raw audio, video, screen, and derived perception streams;
- applying perception enrichment such as voice activity detection;
- routing accepted speech into STT and Persona consumers;
- consuming semantic output streams;
- coordinating text-to-speech synthesis and transcript synchronization;
- handling output interruption and cancellation;
- coordinating future multimodal fusion and interaction decisions;
- keeping provider and transport implementations separate from routing logic.

Voice capabilities such as VAD, STT, and TTS are defined by AlphaAvatar voice abstractions and implemented by voice plugins. The Router decides how those capabilities connect to perception and output streams.

It does not publish directly to LiveKit, a frontend, or another transport.

## ⚙️ Runtime and Processors

`InteractionRouterRuntime` manages the lifecycle of multiple `RouterProcessorBase` implementations.

```text
InteractionRouterRuntime
├── AudioActivityProcessor
├── SpeechTranscriptionProcessor
├── TranscriptSynchronizationProcessor
├── SpeechSynthesisProcessor
└── Future processors
```

The runtime is responsible for:

- starting processors in registration order;
- stopping processors in reverse order;
- rolling back already-started processors when startup fails;
- ensuring processor names are unique.

Each processor owns one independent routing capability:

```python
class RouterProcessorBase:
    @property
    def name(self) -> str: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...
```

Processors may consume perception streams, consume output streams, publish derived observations, publish output events, call injected capabilities, or produce routing decisions.

## 🎙️ Input Flow

The default audio input flow is:

```text
PerceptionRuntime.audio
        ↓
AudioActivityProcessor
        ↓
PerceptionRuntime.speech
        ↓
SpeechTranscriptionProcessor
        ↓
Transcription events
```

### AudioActivityProcessor

Consumes normalized audio frames and uses the injected VAD capability to:

- detect speech activity;
- preserve configurable pre-roll audio;
- publish routed speech frames;
- publish completed audio segments;
- avoid coupling VAD providers to RTC input adapters.

### SpeechTranscriptionProcessor

Consumes routed speech and uses the injected STT capability to:

- process speech without blocking raw audio consumption;
- emit interim, final, and error transcription events;
- keep provider-specific STT behavior outside the Router.

## 🔊 Output Flow

The default transient output flow is:

```text
AUDIO_SYNCED OutputTextChunk
        ↓
SpeechSynthesisProcessor
        ↓
OutputRuntime AudioFrame + Alignment
        ↓
Transport audio adapter
        ↓
OutputRuntime Playback feedback
        ↓
TranscriptSynchronizationProcessor
        ↓
OutputRuntime TranscriptChunk
        ↓
Transport transcript adapter
```

### SpeechSynthesisProcessor

Consumes `AUDIO_SYNCED` source text and uses the injected TTS capability to publish normalized AlphaAvatar audio frames.

One `output_id` owns one long-lived synthesis job. Multiple source-text chunks with the same `output_id` are synthesized sequentially.

A different `output_id` in the same output lane can replace the current output. Interruption cancels the entire synthesis job, removes pending segments, and prevents later chunks from reopening the interrupted output.

The processor also publishes text-audio alignment events that associate a source-text chunk with its generated audio interval.

### TranscriptSynchronizationProcessor

Consumes:

- `TEXT_CHUNK`;
- text-audio `ALIGNMENT`;
- transport `PLAYBACK`;
- `CONTROL` events.

It publishes incremental `TRANSCRIPT_CHUNK` events representing only the text confirmed as delivered by audio playout.

This separates:

```text
generated source text
    what AlphaAvatar intended to say

delivered transcript
    what the user actually heard
```

When audio is interrupted:

- already delivered transcript remains visible;
- unplayed text is not emitted;
- the transcript is finalized with `interrupted=True`;
- the original generated text remains available on the output timeline.

The current fallback synchronizer estimates word or character timing from synthesized audio duration. TTS providers with real word timing can replace this approximation without changing the transport interface.

## 🧩 Supported Processors

| Processor | Input | Output | Function |
| --- | --- | --- | --- |
| `AudioActivityProcessor` | Perception `audio` stream | Perception `speech` stream | Applies injected VAD, preserves pre-roll, and publishes routed speech frames and completed audio segments. |
| `SpeechTranscriptionProcessor` | Perception `speech` stream | Transcription events | Calls injected STT and emits interim, final, and error events without blocking perception consumption. |
| `SpeechSynthesisProcessor` | Output `AUDIO_SYNCED TEXT_CHUNK` | Output `AUDIO_FRAME` and `ALIGNMENT` | Maintains one synthesis job per logical output and converts text into transport-independent audio. |
| `TranscriptSynchronizationProcessor` | Output text, alignment, playback, and control | Output `TRANSCRIPT_CHUNK` | Releases visible text according to actual audio playout and stops at the played boundary after interruption. |

Planned processors may include multimodal understanding, audio classification, visual event detection, intention routing, turn-decision processing, output policy arbitration, and provider-supplied word-alignment processing.

## 🔌 Architectural Boundary

The Router owns routing and processing decisions.

It does not own:

- LiveKit rooms or tracks;
- WebRTC publication;
- frontend rendering;
- provider implementation details;
- persistent memory;
- transport-specific text or audio formats.

The surrounding architecture is:

```text
avatar-core
    perception and output streams, timing, lifecycle, and control semantics

Router
    input/output routing decisions and processor lifecycle

Voice
    VAD, STT, and TTS capability implementations

Entrypoints
    LiveKit and channel transport adapters
```

This boundary supports low-latency, asynchronous, full-duplex operation and allows `livekit.agents` to be removed incrementally.

## 📦 Installation

```bash
pip install alpha-avatar-plugins-router
```

The plugin is loaded through the AlphaAvatar configuration.
