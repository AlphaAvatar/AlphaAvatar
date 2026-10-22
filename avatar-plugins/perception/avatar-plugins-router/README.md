# 🎯 AlphaAvatar Interaction Router Plugin

Router coordinates realtime perception, addressing, turn-taking, synthesis and transcript synchronization through independent processors. It borrows model/voice abstractions and does not publish directly to LiveKit or a frontend.

## ⚙️ Runtime and processors

InteractionRouterRuntime implements `on_start()` / `on_stop()` and delegates ordered processor lifecycle to Core LifecycleGroup through a local adapter. RouterProcessorBase retains its `name`, `start()` and `stop()` interface.

The factory orders consumers according to their dependencies. A processor is an independently owned lifecycle component, not a new task-specific runtime. Startup rollback/closure also covers partial initialization; shutdown failures propagate after ordinary peer cleanup rather than only being logged.

| Processor | Main input | Output |
| --- | --- | --- |
| AudioActivityProcessor | Perception audio | Speech frames and segments with VAD state and pre-roll. |
| SpeechTranscriptionProcessor | Routed speech | Transcript observations with segment provenance. |
| SemanticAddressingProcessor | Transcripts and conversation focus | Typed semantic addressing evidence. |
| VisualAddressingProcessor | Face annotations | Face-orientation addressing evidence. |
| MultimodalTurnTakingProcessor | Speech, transcripts and addressing evidence | Turn decisions. |
| SpeechSynthesisProcessor | AUDIO_SYNCED source text | AudioFrame and text/audio alignment. |
| TranscriptSynchronizationProcessor | Source text, alignment, playback and control | Playback-derived transcript chunks. |

## 🎙️ Audio and transcription

```text
RTC -> PerceptionRuntime.audio -> AudioActivityProcessor
    -> SPEECH_FRAME / SPEECH_SEGMENT -> SpeechTranscriptionProcessor
    -> TRANSCRIPT_SEGMENT
```

Each source owns independent VAD/segmentation state. Pre-roll and bounded queues keep ingestion separate from transcription and model latency. Voice factories come from `runtime.foundation.voice` (VoiceBundle); Router owns borrowed streams/requests, not the factory lifecycle.

## 🎯 Addressing and conversation focus

Semantic Addressing uses configured Avatar aliases, accumulated transcript context and per-speaker focus to classify AVATAR, NON_AVATAR or UNKNOWN. UNKNOWN is abstention, not evidence of another addressee.

Explicit AVATAR/NON_AVATAR evidence updates the speaker's focus; UNKNOWN preserves it. Audio-only interaction can start with an Avatar-directed conversational prior, which explicit non-Avatar evidence overrides. Model implementation stays behind the SemanticAddressingModelBase contract.

VisualAddressingProcessor consumes FACE_DETECTION annotations, smooths orientation scores and publishes subject-scoped evidence. Ambiguous multi-face observations are skipped when the subject cannot be resolved. Face orientation is a heuristic, not a measurement of eye gaze. Gaze, gesture and other future evidence producers can use the same annotation contract.

Addressing fusion preserves provenance, detects conflicting targets and prioritizes explicit current evidence over focus fallback. Provider-specific thresholds stay with the owning model/processor.

## 🔀 Turn decisions and Engine admission

MultimodalTurnTakingProcessor coordinates candidate state, transcript/addressing readiness, asynchronous assessments, stale-result rejection and bounded evidence waits. It publishes COMMIT, HOLD, PASSIVE, INTERRUPT or CANCEL decisions according to its policy.

```text
Speech + transcripts + addressing
    -> TurnTakingCoordinator / policy
    -> perception turn-decision annotation
    -> AvatarEngine
    -> committed Turn and Loop submission / precise interruption
```

Engine now owns admission and native execution scheduling. There is no separate TurnController or SDK response sink. The Router's decision is not itself a model request or a persistence acknowledgement.

AUDIO_ONLY and AUDIO_VISUAL combine the available evidence. VISUAL_ONLY remains an extension point for proactive behavior; its enum or an enabled visual consumer does not imply that proactive visual turns are fully implemented.

## ⚡ Full-duplex interaction

Input, transcription, addressing, model execution, synthesis and playback progress independently. Speech-start interruption need not wait for a final transcript or semantic assessment. After interruption, STT and addressing can continue to determine whether a new committed answer is appropriate.

An old decision cannot gain authority over a newer execution merely by using the same lane. Runtime fixes interruption targets at acceptance; consumers use those exact output/lane/scope identities.

## 🔊 Native output

ASSISTANT and TRANSIENT use the same native output contracts:

```text
EnvOutput(TEXT_CHUNK, AUDIO_SYNCED)
    -> OutputRuntime.publish(...)
    -> SpeechSynthesisProcessor
    -> EnvOutput(AudioFrame / alignment)
    -> RTC audio adapter
    -> playback feedback
    -> TranscriptSynchronizationProcessor
    -> RTC transcript adapter
```

Consumers read `event.output`. Formal scope, model/item provenance, content phase and completion barriers are typed fields rather than execution-significant metadata keys.

One logical output owns its synthesis job. Source chunks are kept in order; replacement or interruption cannot reopen a retired output. Output text preserves whitespace and code indentation. Media publication reuses validated Core audio frames; runtime publication does not re-encode PCM.

TEXT_COMPLETE seals text, AUDIO_COMPLETE seals audio/alignment production, COMPLETE is the Runtime output terminal state, and PLAYBACK is transport delivery evidence. Synthesis, playback and transcript finalization are not collapsed into one generic completion broadcast.

The synchronizer releases text according to played audio. Already delivered transcript remains after interruption; unplayed source text is not reported as heard. Fallback alignment estimates timing from synthesized duration; native provider alignment can improve precision without changing RTC's contract.

IMMEDIATE text does not wait for audio. MIRROR remains observational text for a separately owned delivery path, not a duplicate visible answer. Consumers for unsupported AUDIO_SYNCED output remain present so missing TTS produces an explicit terminal outcome rather than leaving an active output forever.

## ⚙️ Configuration ownership

```text
router.init_config.audio_activity       -> AudioActivityConfig
router.init_config.addressing.semantic  -> SemanticAddressingConfig
router.init_config.addressing.visual    -> VisualAddressingConfig
router.init_config.turn_taking          -> TurnTakingConfig
```

Addressing owns observation/model settings. Turn Taking owns evidence fusion, coordination, interruption and deadlines. `addressing_wait_sec`, `transcript_wait_sec`, `unsegmented_alignment_sec`, `max_hold_sec` and `fusion` belong directly to turn_taking, not its policy subtree.

`interruption.enabled` controls supported Turn interruption; `interruption.audio_only_speech_start` additionally selects immediate audio-only speech-start interruption. There is no parallel `voice.allow_interruptions` switch.

See [Examples](../../../examples/README.md) for full configurations. Disabled optional processors are not constructed; output consumers still honor their explicit unsupported-output handling. Runner selection and model initialization remain separate from processor startup.

## 🔌 Boundaries

Core owns data, timing, state-transition and lifecycle contracts. Router owns interaction processors. Voice owns factories. Persona owns identity processing. Engine owns admission and execution; Host owns assembly; RTC owns codecs, room/track resources and delivery projection.

Router does not own database persistence, transport-specific types, Provider client implementations or another generic event bus. It does not directly consume canonical records as a replacement for Memory/Context consumers.

## 📦 Installation

```bash
pip install alpha-avatar-plugins-router
```

The plugin is selected through Agent configuration. SDK worker/vendor adapters still present elsewhere are not alternative Router generation paths.
