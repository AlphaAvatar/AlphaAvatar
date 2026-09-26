# 🎯 AlphaAvatar Interaction Router Plugin

The Interaction Router coordinates real-time multimodal interaction inside AlphaAvatar.

It connects shared perception, voice, addressing, turn-taking, and output streams through independently managed processors while keeping model providers and transport implementations outside the routing layer.

## 🧭 Module Overview

The Router consumes shared runtime streams and dispatches them through modular processors.

Its responsibilities include:

* consuming raw and derived perception streams;
* detecting speech activity and constructing speech segments;
* routing accepted speech into transcription;
* determining whether speech is addressed to the Avatar;
* maintaining conversation focus across turns;
* coordinating multimodal turn-taking decisions;
* handling interruption, hold, commit, and passive interaction states;
* coordinating text-to-speech synthesis and transcript synchronization;
* exposing interfaces for future visual addressing and multimodal evidence;
* keeping model, provider, and transport implementations separate from routing logic.

Voice capabilities such as VAD, STT, and TTS are defined by AlphaAvatar voice abstractions and implemented by voice plugins.

Semantic addressing and turn-taking models are also exposed through AlphaAvatar Router contracts. Concrete models may be replaced without changing processor or transport logic.

The Router does not publish directly to LiveKit, a frontend, or another transport.

## ⚙️ Runtime and Processors

`InteractionRouterRuntime` manages the lifecycle of multiple `RouterProcessorBase` implementations.

```text
InteractionRouterRuntime
├── AudioActivityProcessor
├── SpeechTranscriptionProcessor
├── SemanticAddressingProcessor
├── VisualAddressingProcessor
├── MultimodalTurnTakingProcessor
├── SpeechSynthesisProcessor
└── TranscriptSynchronizationProcessor
```

The runtime is responsible for:

* starting processors in registration order;
* stopping processors in reverse order;
* rolling back already-started processors when startup fails;
* ensuring processor names are unique.

Each processor owns one independent routing capability:

```python
class RouterProcessorBase:
    @property
    def name(self) -> str: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...
```

Processors may consume perception streams, publish derived observations and annotations, call injected capabilities, coordinate asynchronous inference, consume output streams, publish output events, or produce interaction decisions.

## 🎙️ Audio and Transcription Flow

The default audio input flow is:

```text
PerceptionRuntime.audio
        ↓
AudioActivityProcessor
        ↓
SPEECH_FRAME / SPEECH_SEGMENT
        ↓
SpeechTranscriptionProcessor
        ↓
TRANSCRIPT_SEGMENT
```

### AudioActivityProcessor

Consumes normalized audio frames and uses the injected VAD capability to:

* detect speech activity;
* maintain independent state for each audio source;
* preserve configurable pre-roll audio;
* publish routed speech frames;
* publish completed speech segments;
* isolate VAD providers from RTC input adapters.

Each audio source owns an independent VAD stream and segmentation state, allowing multiple realtime sources to progress without blocking each other.

### SpeechTranscriptionProcessor

Consumes routed speech and uses the injected STT capability to:

* process speech independently from raw audio consumption;
* publish transcript observations aligned with speech segments;
* keep provider-specific STT behavior outside the Router;
* provide transcript segments to addressing and turn-taking processors.

## 🎯 Semantic Addressing

Semantic Addressing determines whether the current speech is directed at the Avatar.

```text
TRANSCRIPT_SEGMENT
        ↓
SemanticAddressingProcessor
        ↓
SemanticAddressingModelBase
        ↓
AVATAR / NON_AVATAR / UNKNOWN
        ↓
INTERACTION_ADDRESSING_EVIDENCE
```

The model receives contextual information including:

* configured Avatar identities and aliases;
* conversation focus at the beginning of the current turn;
* recent configurable conversation history;
* transcript segments accumulated for the current turn.

One assessment is performed for each completed speech segment.

The processor does not depend on a specific model repository or inference backend. Concrete Semantic Addressing models are isolated behind `SemanticAddressingModelBase` and may use local CPU inference, remote inference, or future model implementations.

### Addressing Labels

Semantic Addressing uses three runtime outcomes:

```text
AVATAR
    explicit evidence that speech is directed at the Avatar

NON_AVATAR
    explicit evidence that speech is directed elsewhere

UNKNOWN
    insufficient evidence; abstain from changing the current focus
```

`UNKNOWN` is not treated as evidence that the user is speaking to another person.

### Conversation Focus

Semantic Addressing maintains conversation focus independently for each speaker.

```text
AVATAR
    → focus becomes AVATAR

NON_AVATAR
    → focus becomes NON_AVATAR

UNKNOWN
    → existing focus is preserved
```

This allows interactions such as:

```text
User talks to Avatar
        ↓
focus = AVATAR

User clearly turns to another person
        ↓
focus = NON_AVATAR

Ambiguous follow-up speech
        ↓
focus remains NON_AVATAR

User explicitly addresses Avatar again
        ↓
focus = AVATAR
```

For audio-only interaction, the initial conversational prior is that the user is addressing the Avatar. Explicit `NON_AVATAR` evidence can override that prior, while `UNKNOWN` does not.

## 👁️ Visual Addressing

`VisualAddressingProcessor` consumes `FACE_DETECTION` annotations and uses `FaceOrientationEstimator` to produce visual addressing evidence.

The processor maintains independent state for each visual subject, smooths orientation scores, applies configurable thresholds, and limits repeated evidence publication. Ambiguous multi-face observations are skipped when the active subject cannot be identified reliably.

Face orientation provides heuristic addressing evidence; it is not a direct measurement of eye gaze.

Gaze direction, body orientation, gestures, scene events, and other visual attention signals remain extension points. Additional producers can publish the same addressing annotation contract without changing the Turn Taking processor.

## 🔀 Addressing Fusion

Addressing producers publish independent `INTERACTION_ADDRESSING_EVIDENCE` annotations.

```text
Semantic Addressing ─────┐
Conversation Focus ──────┤
Visual Addressing ───────┤
Explicit Evidence ───────┤
                         ↓
                Addressing Fusion
                         ↓
              resolved addressee
```

The fusion layer:

* ignores abstaining `UNKNOWN` evidence;
* keeps evidence providers independent;
* resolves compatible evidence;
* detects conflicting targets;
* preserves evidence provenance;
* allows current explicit evidence to take priority over conversation-focus fallback.

Model-specific thresholds remain inside the model or processor that owns them rather than inside the generic fusion layer.

## 🔄 Multimodal Turn Taking

`MultimodalTurnTakingProcessor` combines speech state, transcripts, addressing evidence, and turn-taking model assessments into interaction decisions.

```text
Speech / Transcript
        │
        ├───────────────→ Turn Taking Model
        │
Addressing Evidence
        │
        └───────────────→ Addressing Fusion
                                │
                                ↓
                     TurnTakingCoordinator
                                │
                                ↓
                      TurnTakingPolicy
                                │
              ┌─────────────────┼─────────────────┐
              ↓                 ↓                 ↓
           COMMIT              HOLD            PASSIVE
              │                                   │
              └──────── INTERRUPT / CANCEL ───────┘
```

The coordinator manages:

* turn candidates;
* speech segment lifecycle;
* transcript readiness;
* addressing readiness;
* asynchronous model assessments;
* stale-result rejection;
* interruption handling;
* timeout resolution;
* evidence alignment;
* terminal turn decisions.

Semantic Addressing and Turn Taking inference may execute independently and asynchronously. The coordinator waits only for required evidence within configured latency bounds.

### Turn Modes

The Router supports:

```text
AUDIO_ONLY
AUDIO_VISUAL
VISUAL_ONLY
```

`AUDIO_ONLY` assumes the Avatar as the initial conversational target when no explicit addressing evidence exists.

Explicit `NON_AVATAR` evidence may suppress a response, while ambiguous or missing evidence can fall back to the audio-only conversational prior.

`AUDIO_VISUAL` can combine semantic, conversational, and face-orientation evidence.

`VISUAL_ONLY` is reserved for future proactive and observation-driven interaction behavior.

## ⚡ Full-Duplex Interaction

The Router is designed for low-latency, asynchronous, full-duplex operation.

Independent processors allow perception, transcription, semantic addressing, turn-taking inference, synthesis, and playback feedback to progress concurrently.

For example:

```text
Avatar speaking
      │
      ├──────── User speech begins
      │              ↓
      │       speech-start detection
      │              ↓
      └────────── INTERRUPT
                     ↓
                 Avatar stops
                     ↓
              STT continues
                     ↓
        Semantic Addressing resolves
                     ↓
             COMMIT / PASSIVE
```

Interruption does not require waiting for a completed semantic assessment. The Avatar can stop output immediately when new speech begins and determine the actual addressee asynchronously afterward.

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

The processor also publishes text-audio alignment events associating source-text chunks with generated audio intervals.

### TranscriptSynchronizationProcessor

Consumes:

* `TEXT_CHUNK`;
* text-audio `ALIGNMENT`;
* transport `PLAYBACK`;
* `CONTROL` events.

It publishes incremental `TRANSCRIPT_CHUNK` events representing only text confirmed as delivered through audio playout.

This separates:

```text
generated source text
    what AlphaAvatar intended to say

delivered transcript
    what the user actually heard
```

When audio is interrupted:

* already delivered transcript remains visible;
* unplayed text is not emitted;
* the transcript is finalized with `interrupted=True`;
* the original generated text remains available on the output timeline.

The current fallback synchronizer estimates word or character timing from synthesized audio duration. TTS providers with native word timing can replace this approximation without changing the transport interface.

## 🧩 Supported Processors

| Processor                            | Input                                         | Output                                    | Function                                                                                             |
| ------------------------------------ | --------------------------------------------- | ----------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `AudioActivityProcessor`             | Perception `audio`                            | `SPEECH_FRAME`, `SPEECH_SEGMENT`          | Applies VAD, maintains per-source speech state, preserves pre-roll, and publishes segmented speech.  |
| `SpeechTranscriptionProcessor`       | Routed speech                                 | `TRANSCRIPT_SEGMENT`                      | Calls injected STT and publishes transcript observations without blocking audio processing.          |
| `SemanticAddressingProcessor`        | Transcript segments                           | `INTERACTION_ADDRESSING_EVIDENCE`         | Determines whether speech is directed at the Avatar and maintains per-speaker conversation focus.    |
| `VisualAddressingProcessor`          | `FACE_DETECTION` annotations                  | `INTERACTION_ADDRESSING_EVIDENCE`         | Estimates face orientation, smooths per-subject scores, and publishes visual addressing evidence.    |
| `MultimodalTurnTakingProcessor`      | Speech, transcript, and addressing evidence   | Turn decisions and addressing annotations | Coordinates turn state, evidence fusion, interruption, commit, hold, and passive behavior.           |
| `SpeechSynthesisProcessor`           | Output `AUDIO_SYNCED TEXT_CHUNK`              | `AUDIO_FRAME`, `ALIGNMENT`                | Maintains synthesis jobs and converts text into transport-independent audio.                         |
| `TranscriptSynchronizationProcessor` | Output text, alignment, playback, and control | `TRANSCRIPT_CHUNK`                        | Releases visible transcript according to actual audio playout.                                       |

## ⚙️ Configuration Ownership

The top-level `RouterConfig` composes processor-owned configurations. `RouterPlugin` validates the configuration, selects enabled processors, and passes only the corresponding configuration subtree to each processor.

```text
router.init_config.audio_activity
    → AudioActivityConfig

router.init_config.addressing.semantic
    → SemanticAddressingConfig

router.init_config.addressing.visual
    → VisualAddressingConfig

router.init_config.turn_taking
    → TurnTakingConfig
```

Addressing producers own their observation and model settings. Turn Taking owns evidence coordination, fusion, interruption policy, and timeout settings.

`addressing_wait_sec`, `transcript_wait_sec`, `unsegmented_alignment_sec`, `max_hold_sec`, and `fusion` belong directly to `turn_taking`. The `policy` section contains decision-policy settings such as `commit_threshold` and `respond_to_group`.

`interruption.enabled` controls interruption across supported turn modes. `interruption.audio_only_speech_start` additionally controls immediate speech-start interruption in audio-only mode.

Disabled processors are not constructed by `RouterPlugin`. Inference runner registration and model initialization are managed separately.

## 🔌 Architectural Boundary

The Router owns realtime interaction routing and coordination.

It does not own:

* LiveKit rooms or tracks;
* WebRTC publication;
* frontend rendering;
* model provider implementations;
* persistent memory;
* transport-specific text or audio formats.

The surrounding architecture is:

```text
avatar-core
    perception and output streams, timing, annotations, lifecycle, and control semantics

Router
    realtime perception routing, addressing, turn taking, and output coordination

Voice
    VAD, STT, and TTS capability implementations

Persona
    identity, speaker, face, and user-context processing

Entrypoints
    LiveKit and channel transport adapters
```

This boundary supports low-latency, asynchronous, modular, full-duplex interaction while allowing perception models, voice providers, semantic addressing models, turn-taking models, and transports to evolve independently.

## 📦 Installation

```bash
pip install alpha-avatar-plugins-router
```

The plugin is loaded through the AlphaAvatar configuration.
